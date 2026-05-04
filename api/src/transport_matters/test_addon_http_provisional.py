from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, cast

from transport_matters import addon as addon_module
from transport_matters import addon_handlers
from transport_matters import breakpoint as bp
from transport_matters.addon import ManicureAddon
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
from transport_matters.pause_session import handle_breakpoint

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
        "_persist_http_provisional_exchange",
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
        "_persist_http_provisional_exchange",
        fake_persist,
    )

    await addon_handlers.handle_http_request(flow, None)

    state = get_request_flow_state(flow)
    assert calls == 1
    assert state is not None
    assert state.provisional_exchange_id is None
    assert json.loads(cast("_Flow", flow).request.text)["system"][0]["text"] == (
        "curated system"
    )


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


async def test_addon_error_deletes_http_provisional_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    ir = _curated_ir()
    capture_request_flow_state(
        flow, adapter=object(), request_ir=ir, raw_request=b"raw"
    )
    state = update_request_flow_state(flow, provisional_exchange_id="exchange-error")
    assert state is not None
    calls: list[tuple[http.HTTPFlow, RequestFlowState]] = []

    async def fake_delete(
        delete_flow: http.HTTPFlow,
        delete_state: RequestFlowState,
    ) -> bool:
        calls.append((delete_flow, delete_state))
        return True

    monkeypatch.setattr(addon_module, "_delete_http_provisional_exchange", fake_delete)

    await ManicureAddon().error(flow)

    assert calls == [(flow, state)]


async def test_addon_error_skips_codex_websocket_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    cast("_Flow", flow).request = _Request(
        host=CODEX_CHATGPT_HOST,
        path=CODEX_RESPONSES_PATH,
    )
    ir = _curated_ir()
    capture_request_flow_state(
        flow, adapter=object(), request_ir=ir, raw_request=b"raw"
    )
    update_request_flow_state(flow, provisional_exchange_id="exchange-codex")

    async def fail_delete(*args: object) -> bool:
        raise AssertionError("Codex websocket error hook path must be a no-op")

    monkeypatch.setattr(addon_module, "_delete_http_provisional_exchange", fail_delete)

    await ManicureAddon().error(flow)


async def test_addon_error_skips_when_request_state_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    assert get_request_flow_state(flow) is None

    async def fail_delete(*args: object) -> bool:
        raise AssertionError("Missing request state must short-circuit error hook")

    monkeypatch.setattr(addon_module, "_delete_http_provisional_exchange", fail_delete)

    await ManicureAddon().error(flow)


async def test_addon_error_skips_when_provisional_exchange_id_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    ir = _curated_ir()
    capture_request_flow_state(
        flow, adapter=object(), request_ir=ir, raw_request=b"raw"
    )

    async def fail_delete(*args: object) -> bool:
        raise AssertionError("Missing provisional id must short-circuit error hook")

    monkeypatch.setattr(addon_module, "_delete_http_provisional_exchange", fail_delete)

    await ManicureAddon().error(flow)
