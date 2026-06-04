import asyncio
import json
import types
from typing import TYPE_CHECKING, cast

from transport_matters import addon as addon_module
from transport_matters import addon_handlers
from transport_matters import breakpoint as bp
from transport_matters.addon import TransportMattersAddon
from transport_matters.codex.transport import CODEX_CHATGPT_HOST, CODEX_RESPONSES_PATH
from transport_matters.flow_state import (
    RequestFlowState,
    capture_request_flow_state,
    get_request_flow_state,
    update_request_flow_state,
)
from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
)
from transport_matters.pause_session import _release_payload, handle_breakpoint

if TYPE_CHECKING:
    import pytest
    from mitmproxy import http


class _Flow:
    def __init__(self) -> None:
        self.id = "flow-http-hook"
        self.metadata: dict[str, object] = {}
        self.request = _Request()


class _Request:
    def __init__(
        self,
        *,
        host: str = "api.anthropic.com",
        path: str = "/v1/messages",
    ) -> None:
        self.host = host
        self.path = path
        self.method = "POST"
        self.headers = {"x-api-key": "test-key"}
        self.text = json.dumps(
            {
                "model": "claude-3-5-sonnet",
                "system": [{"type": "text", "text": "original system"}],
                "max_tokens": 1024,
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "hello"}],
                    }
                ],
            }
        )

    def get_text(self) -> str:
        return self.text

    def set_text(self, text: str) -> None:
        self.text = text


def _curated_ir() -> InternalRequest:
    return InternalRequest(
        model="anthropic/claude-3-5-sonnet",
        provider="anthropic",
        system=[SystemPart(text="curated system")],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hello")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


async def _fake_run_pipeline(
    ir: InternalRequest,
    flow_id: str,
    run_id: str | None,
) -> tuple[InternalRequest, None, None]:
    return _curated_ir(), None, None


def _codex_ir() -> InternalRequest:
    return _curated_ir().model_copy(update={"model": "codex/gpt-5-codex", "provider": "codex"})


class _FakeCodexAdapter:
    def inbound_request(self, raw_body: bytes) -> InternalRequest:
        return _codex_ir()

    def outbound_request(self, ir: InternalRequest) -> bytes:
        return b'{"model":"gpt-5-codex"}'


async def test_http_request_persists_provisional_exchange_before_breakpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    events: list[str] = []

    async def fake_persist(
        persist_flow: http.HTTPFlow,
        state: RequestFlowState,
    ) -> str:
        assert persist_flow is flow
        assert state.curated_request_ir.system[0].text == "curated system"
        events.append("persist")
        return "exchange-hook"

    async def fake_handle_breakpoint(*args: object) -> None:
        state = get_request_flow_state(flow)
        assert state is not None
        assert state.provisional_exchange_id == "exchange-hook"
        events.append("breakpoint")

    monkeypatch.setattr(addon_handlers, "run_pipeline", _fake_run_pipeline)
    monkeypatch.setattr(
        addon_handlers,
        "persist_http_provisional_exchange",
        fake_persist,
    )
    monkeypatch.setattr(bp, "is_armed", lambda: True)
    monkeypatch.setattr(addon_handlers, "handle_breakpoint", fake_handle_breakpoint)

    await addon_handlers.handle_http_request(flow, None)

    assert events == ["persist", "breakpoint"]


async def test_http_request_leaves_flow_clean_when_provisional_persist_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    calls = 0

    async def fake_persist(
        persist_flow: http.HTTPFlow,
        state: RequestFlowState,
    ) -> None:
        nonlocal calls
        calls += 1
        assert persist_flow is flow
        assert state.provisional_exchange_id is None
        return

    monkeypatch.setattr(addon_handlers, "run_pipeline", _fake_run_pipeline)
    monkeypatch.setattr(addon_handlers, "_should_skip_breakpoint", lambda model: True)
    monkeypatch.setattr(
        addon_handlers,
        "persist_http_provisional_exchange",
        fake_persist,
    )

    await addon_handlers.handle_http_request(flow, None)

    state = get_request_flow_state(flow)
    assert calls == 1
    assert state is not None
    assert state.provisional_exchange_id is None
    assert json.loads(cast("_Flow", flow).request.text)["system"][0]["text"] == ("curated system")


async def test_http_request_preserves_original_bytes_when_pipeline_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    original_text = cast("_Flow", flow).request.text

    async def noop_pipeline(
        ir: InternalRequest,
        flow_id: str,
        run_id: str | None,
    ) -> tuple[InternalRequest, None, None]:
        return ir, None, None

    async def fake_persist(
        persist_flow: http.HTTPFlow,
        state: RequestFlowState,
    ) -> str:
        return "exchange-noop"

    monkeypatch.setattr(addon_handlers, "run_pipeline", noop_pipeline)
    monkeypatch.setattr(addon_handlers, "_should_skip_breakpoint", lambda model: True)
    monkeypatch.setattr(
        addon_handlers,
        "persist_http_provisional_exchange",
        fake_persist,
    )

    await addon_handlers.handle_http_request(flow, None)

    # Pipeline changed nothing, so the captured wire bytes must pass through
    # untouched rather than being reserialized (which reorders JSON keys).
    assert cast("_Flow", flow).request.text == original_text


async def test_codex_http_request_snapshots_current_identity_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    request = cast("_Flow", flow).request
    request.host = CODEX_CHATGPT_HOST
    request.path = CODEX_RESPONSES_PATH
    request.headers = {
        "session-id": "session-1",
        "thread-id": "thread-1",
        "x-codex-turn-metadata": '{"turn_id":"turn-1"}',
        "authorization": "Bearer secret",
        "session_id": "legacy-session",
    }

    async def fake_pipeline(
        ir: InternalRequest,
        flow_id: str,
        run_id: str | None,
    ) -> tuple[InternalRequest, None, None]:
        return ir, None, None

    async def fake_persist(
        persist_flow: http.HTTPFlow,
        state: RequestFlowState,
    ) -> None:
        assert persist_flow is flow
        assert state.codex_request_headers == {
            "session-id": "session-1",
            "thread-id": "thread-1",
            "x-codex-turn-metadata": '{"turn_id":"turn-1"}',
        }

    monkeypatch.setattr(addon_handlers, "get_adapter", lambda flow: _FakeCodexAdapter())
    monkeypatch.setattr(addon_handlers, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(addon_handlers, "_should_skip_breakpoint", lambda model: True)
    monkeypatch.setattr(
        addon_handlers,
        "persist_http_provisional_exchange",
        fake_persist,
    )

    await addon_handlers.handle_http_request(flow, None)

    state = get_request_flow_state(flow)
    assert state is not None
    assert state.codex_request_headers["thread-id"] == "thread-1"


class _WSAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def outbound_request(self, ir: InternalRequest) -> bytes:
        self.calls += 1
        return b"reserialized-frame"


class _WSMessage:
    def __init__(self) -> None:
        self.from_client = True
        self.is_text = True
        self.content: bytes = b"ORIGINAL_FRAME"


class _WSState:
    def __init__(self) -> None:
        self.provisional_exchange_id: str | None = None
        self.client_message_count = 1
        self.server_message_count = 0
        self.initial_client_frame: bytes = b"frame"
        self.finalized_exchange_id: str | None = None
        self.turn_start_message_index = 0
        self.turn_client_messages_before = 0
        self.turn_server_messages_before = 0


def _drive_codex_ws_noop(
    monkeypatch: pytest.MonkeyPatch,
    adapter: _WSAdapter,
    message: _WSMessage,
    curated_ir: InternalRequest,
) -> http.HTTPFlow:
    state = _WSState()
    flow = cast(
        "http.HTTPFlow",
        types.SimpleNamespace(id="flow-ws", websocket=types.SimpleNamespace(messages=[object()])),
    )
    ir = _codex_ir()

    async def noop_pipeline(
        req: InternalRequest,
        flow_id: str,
        run_id: str | None,
    ) -> tuple[InternalRequest, None, None]:
        return curated_ir, None, None

    async def noop_persist(persist_flow: http.HTTPFlow) -> None:
        return None

    monkeypatch.setattr(
        addon_handlers,
        "record_codex_websocket_message",
        lambda f: (state, message, True),
    )
    monkeypatch.setattr(addon_handlers, "clear_codex_breakpoint_lifecycle", lambda f: None)
    monkeypatch.setattr(addon_handlers, "capture_codex_initial_request_ir", lambda f, frame: ir)
    monkeypatch.setattr(
        addon_handlers,
        "get_request_flow_state",
        lambda f: types.SimpleNamespace(adapter=adapter),
    )
    monkeypatch.setattr(addon_handlers, "run_pipeline", noop_pipeline)
    monkeypatch.setattr(addon_handlers, "update_request_flow_state", lambda *a, **k: None)
    monkeypatch.setattr(addon_handlers, "persist_codex_provisional_exchange", noop_persist)
    monkeypatch.setattr(addon_handlers, "_should_skip_breakpoint", lambda model: True)
    return flow


async def test_codex_ws_preserves_original_frame_when_pipeline_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _WSAdapter()
    message = _WSMessage()
    # Pipeline returns the same IR capture produces, so curated == original.
    flow = _drive_codex_ws_noop(monkeypatch, adapter, message, _codex_ir())

    await addon_handlers.handle_codex_websocket_message(flow)

    assert message.content == b"ORIGINAL_FRAME"
    assert adapter.calls == 0


async def test_codex_ws_reserializes_frame_when_pipeline_changes_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _WSAdapter()
    message = _WSMessage()
    curated = _codex_ir().model_copy(update={"model": "codex/edited"})
    flow = _drive_codex_ws_noop(monkeypatch, adapter, message, curated)

    await addon_handlers.handle_codex_websocket_message(flow)

    assert message.content == b"reserialized-frame"
    assert adapter.calls == 1


class _DropFlow(_Flow):
    def __init__(self) -> None:
        super().__init__()
        self._response: object | None = None
        self.response_set_saw_dropped: bool | None = None

    @property
    def response(self) -> object | None:
        return self._response

    @response.setter
    def response(self, value: object) -> None:
        state = get_request_flow_state(cast("http.HTTPFlow", self))
        self.response_set_saw_dropped = state.dropped if state is not None else None
        self._response = value


async def test_http_breakpoint_drop_marks_state_before_synthetic_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _DropFlow())
    ir = _curated_ir()
    capture_request_flow_state(
        flow,
        adapter=object(),
        request_ir=ir,
        raw_request=b"raw",
        curated_request_ir=ir,
    )
    update_request_flow_state(flow, provisional_exchange_id="exchange-drop")

    paused = bp.PausedFlow(
        flow=flow,
        event=asyncio.Event(),
        original_ir=ir,
        curated_ir=ir,
        paused_at_ms=0,
        dropped=True,
    )
    paused.event.set()

    async def fake_pause(*args: object, **kwargs: object) -> asyncio.Event:
        return paused.event

    async def fake_pop_paused(flow_id: str) -> bp.PausedFlow:
        assert flow_id == flow.id
        return paused

    monkeypatch.setattr(bp, "pause", fake_pause)
    monkeypatch.setattr(bp, "pop_paused", fake_pop_paused)

    await handle_breakpoint(flow, object(), ir, ir, None, None)

    state = get_request_flow_state(flow)
    assert state is not None
    assert state.dropped is True
    assert cast("_DropFlow", flow).response_set_saw_dropped is True


def _paused(
    original: InternalRequest,
    curated: InternalRequest,
    *,
    mutated_ir: InternalRequest | None = None,
    release_payload: bytes | None = None,
) -> bp.PausedFlow:
    return bp.PausedFlow(
        flow=cast("http.HTTPFlow", _Flow()),
        event=asyncio.Event(),
        original_ir=original,
        curated_ir=curated,
        paused_at_ms=0,
        mutated_ir=mutated_ir,
        release_payload=release_payload,
    )


def test_release_payload_none_when_unchanged_and_no_user_payload() -> None:
    ir = _curated_ir()
    adapter = _WSAdapter()
    assert _release_payload(_paused(ir, ir), adapter, ir) is None
    assert adapter.calls == 0


def test_release_payload_returns_user_payload_verbatim() -> None:
    ir = _curated_ir()
    adapter = _WSAdapter()
    pf = _paused(ir, ir, release_payload=b"USER_EDIT")
    assert _release_payload(pf, adapter, ir) == b"USER_EDIT"
    assert adapter.calls == 0


def test_release_payload_serializes_when_final_ir_changed() -> None:
    original = _curated_ir()
    changed = original.model_copy(update={"model": "edited"})
    adapter = _WSAdapter()
    pf = _paused(original, changed, mutated_ir=changed)
    assert _release_payload(pf, adapter, changed) == b"reserialized-frame"
    assert adapter.calls == 1


async def test_http_breakpoint_release_preserves_original_bytes_when_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    original_text = cast("_Flow", flow).request.text
    ir = _curated_ir()
    capture_request_flow_state(
        flow, adapter=object(), request_ir=ir, raw_request=b"raw", curated_request_ir=ir
    )
    adapter = _WSAdapter()
    paused = _paused(ir, ir)
    paused.event.set()

    async def fake_pause(*args: object, **kwargs: object) -> asyncio.Event:
        return paused.event

    async def fake_pop_paused(flow_id: str) -> bp.PausedFlow:
        return paused

    monkeypatch.setattr(bp, "pause", fake_pause)
    monkeypatch.setattr(bp, "pop_paused", fake_pop_paused)

    await handle_breakpoint(flow, adapter, ir, ir, None, None)

    # Released unchanged with no manual edit: keep the original wire bytes.
    assert cast("_Flow", flow).request.text == original_text
    assert adapter.calls == 0


async def test_addon_error_deletes_http_provisional_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    ir = _curated_ir()
    capture_request_flow_state(flow, adapter=object(), request_ir=ir, raw_request=b"raw")
    state = update_request_flow_state(flow, provisional_exchange_id="exchange-error")
    assert state is not None
    calls: list[tuple[http.HTTPFlow, RequestFlowState]] = []

    async def fake_delete(
        delete_flow: http.HTTPFlow,
        delete_state: RequestFlowState,
    ) -> bool:
        calls.append((delete_flow, delete_state))
        return True

    monkeypatch.setattr(addon_module, "delete_http_provisional_exchange", fake_delete)

    await TransportMattersAddon().error(flow)

    assert calls == [(flow, state)]


async def test_addon_error_skips_codex_websocket_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    cast("_Flow", flow).request = _Request(
        host=CODEX_CHATGPT_HOST,
        path=CODEX_RESPONSES_PATH,
    )
    cast("_Flow", flow).request.headers["Upgrade"] = "websocket"
    ir = _curated_ir()
    capture_request_flow_state(flow, adapter=object(), request_ir=ir, raw_request=b"raw")
    update_request_flow_state(flow, provisional_exchange_id="exchange-codex")

    async def fail_delete(*args: object) -> bool:
        raise AssertionError("Codex websocket error hook path must be a no-op")

    monkeypatch.setattr(addon_module, "delete_http_provisional_exchange", fail_delete)

    await TransportMattersAddon().error(flow)


async def test_addon_error_skips_when_request_state_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    assert get_request_flow_state(flow) is None

    async def fail_delete(*args: object) -> bool:
        raise AssertionError("Missing request state must short-circuit error hook")

    monkeypatch.setattr(addon_module, "delete_http_provisional_exchange", fail_delete)

    await TransportMattersAddon().error(flow)


async def test_addon_error_skips_when_provisional_exchange_id_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    ir = _curated_ir()
    capture_request_flow_state(flow, adapter=object(), request_ir=ir, raw_request=b"raw")

    async def fail_delete(*args: object) -> bool:
        raise AssertionError("Missing provisional id must short-circuit error hook")

    monkeypatch.setattr(addon_module, "delete_http_provisional_exchange", fail_delete)

    await TransportMattersAddon().error(flow)


async def test_http_request_records_unparsed_exchange_on_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    original_text = cast("_Flow", flow).request.text
    calls: list[tuple[http.HTTPFlow, object, bool]] = []

    async def fake_parse(
        parse_flow: http.HTTPFlow,
        adapter: object,
    ) -> None:
        return None

    async def fake_unparsed(
        record_flow: http.HTTPFlow,
        adapter: object,
        codex_http: bool,
    ) -> None:
        calls.append((record_flow, adapter, codex_http))

    async def fail_persist(*args: object, **kwargs: object) -> str:
        raise AssertionError("parse failure must not reach the happy path")

    monkeypatch.setattr(addon_handlers, "get_adapter", lambda flow: object())
    monkeypatch.setattr(addon_handlers, "parse_request_ir", fake_parse)
    monkeypatch.setattr(addon_handlers, "persist_unparsed_http_exchange", fake_unparsed)
    monkeypatch.setattr(addon_handlers, "persist_http_provisional_exchange", fail_persist)

    await addon_handlers.handle_http_request(flow, None)

    assert len(calls) == 1
    assert calls[0][0] is flow
    assert calls[0][2] is False
    # The wire bytes must pass through untouched on the failure path.
    assert cast("_Flow", flow).request.text == original_text


async def test_codex_ws_records_unparsed_exchange_when_initial_frame_unparsable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _WSState()
    state.initial_client_frame = b"unparsable-frame"
    message = _WSMessage()
    flow = cast(
        "http.HTTPFlow",
        types.SimpleNamespace(
            id="flow-ws-unparsed",
            websocket=types.SimpleNamespace(messages=[object()]),
        ),
    )
    calls: list[tuple[http.HTTPFlow, bytes]] = []

    async def fake_unparsed(record_flow: http.HTTPFlow, raw_frame: bytes) -> None:
        calls.append((record_flow, raw_frame))

    async def fail_pipeline(*args: object, **kwargs: object) -> object:
        raise AssertionError("unparsable frame must not reach the pipeline")

    monkeypatch.setattr(
        addon_handlers,
        "record_codex_websocket_message",
        lambda f: (state, message, True),
    )
    monkeypatch.setattr(addon_handlers, "clear_codex_breakpoint_lifecycle", lambda f: None)
    monkeypatch.setattr(addon_handlers, "capture_codex_initial_request_ir", lambda f, frame: None)
    monkeypatch.setattr(addon_handlers, "clear_request_flow_state", lambda f: None)
    monkeypatch.setattr(addon_handlers, "persist_unparsed_codex_exchange", fake_unparsed)
    monkeypatch.setattr(addon_handlers, "run_pipeline", fail_pipeline)

    await addon_handlers.handle_codex_websocket_message(flow)

    assert calls == [(flow, b"unparsable-frame")]
    # Transparency: the client frame on the wire is never rewritten.
    assert message.content == b"ORIGINAL_FRAME"
