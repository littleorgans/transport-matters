from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from mitmproxy import http

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

import transport_matters.addon_handlers as addon_handlers
import transport_matters.breakpoint as bp
import transport_matters.shared_proxy.addon as shared_proxy_addon
from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
)
from transport_matters.response_stream import _STREAM_BUFFER_KEY
from transport_matters.shared_proxy.addon import (
    FLOW_LISTEN_PORT_METADATA_KEY,
    FLOW_RUN_ID_METADATA_KEY,
    SharedProxyAddon,
    SharedProxyBindingTable,
    SharedProxyDemuxMetrics,
)
from transport_matters.shared_proxy.binding import ProxyRunBinding
from transport_matters.shared_proxy.models import binding_payload_from_binding
from transport_matters.storage.disk import DiskStorageBackend

if TYPE_CHECKING:
    from transport_matters.flow_state import RequestFlowState


class _ProxyMode:
    def __init__(self, custom_listen_port: int | None) -> None:
        self.custom_listen_port = custom_listen_port


class _ClientConn:
    def __init__(self, *, listen_port: int, custom_listen_port: int | None = None) -> None:
        self.sockname: tuple[str, int] | None = ("127.0.0.1", listen_port)
        self.proxy_mode = _ProxyMode(
            listen_port if custom_listen_port is None else custom_listen_port
        )


class _Request:
    def __init__(self) -> None:
        self.host = "api.anthropic.com"
        self.path = "/v1/messages"
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


class _WebSocket:
    def __init__(self) -> None:
        self.messages: list[object] = []
        self.closed_by_client: bool | None = None
        self.close_code: int | None = None
        self.close_reason: str | None = None
        self.timestamp_end: float | None = None


class _Flow:
    def __init__(
        self,
        flow_id: str,
        *,
        listen_port: int,
        custom_listen_port: int | None = None,
        websocket: bool = False,
    ) -> None:
        self.id = flow_id
        self.metadata: dict[str, object] = {}
        self.request = _Request()
        self.response: http.Response | None = None
        self.client_conn = _ClientConn(
            listen_port=listen_port,
            custom_listen_port=custom_listen_port,
        )
        self.server_conn = SimpleNamespace(timestamp_start=None)
        self.websocket = _WebSocket() if websocket else None
        self.killed = False
        self.live = True

    @property
    def killable(self) -> bool:
        return True

    def kill(self) -> None:
        self.killed = True
        self.live = False


SeenEvent = tuple[str, str, str | None, str | None, int | None]


def _set_demux_metadata(
    flow: _Flow,
    *,
    run_id: str | None = None,
    listen_port: int | None = None,
) -> None:
    if run_id is not None:
        flow.metadata[FLOW_RUN_ID_METADATA_KEY] = run_id
    if listen_port is not None:
        flow.metadata[FLOW_LISTEN_PORT_METADATA_KEY] = listen_port


def _install_recording_http_kernel(
    monkeypatch: pytest.MonkeyPatch,
    seen: list[SeenEvent],
) -> None:
    async def fake_run_pipeline(
        ir: InternalRequest,
        flow_id: str,
        run_id: str | None,
    ) -> tuple[InternalRequest, None, None]:
        seen.append(("pipeline", flow_id, run_id, None, None))
        return _curated_ir(), None, None

    async def fake_persist_provisional(
        flow: http.HTTPFlow,
        state: RequestFlowState,
        binding: ProxyRunBinding | None = None,
    ) -> str:
        assert binding is not None
        seen.append(
            (
                "provisional",
                flow.id,
                binding.run_id,
                _storage_root(binding),
                state.listen_port,
            )
        )
        return f"exchange-{binding.run_id}"

    async def fake_persist_final(
        flow: http.HTTPFlow,
        state: RequestFlowState,
        token_counter: object | None,
        binding: ProxyRunBinding | None = None,
    ) -> None:
        assert binding is not None
        seen.append(
            (
                "final",
                flow.id,
                state.run_id,
                _storage_root(binding),
                state.listen_port,
            )
        )

    monkeypatch.setattr(addon_handlers, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(
        addon_handlers,
        "persist_http_provisional_exchange",
        fake_persist_provisional,
    )
    monkeypatch.setattr(addon_handlers, "persist_http_exchange", fake_persist_final)
    monkeypatch.setattr(bp, "is_armed", lambda: False)


def _guard_kernel(monkeypatch: pytest.MonkeyPatch, called: list[str]) -> None:
    async def fake_async(*args: object, **kwargs: object) -> None:
        called.append("kernel")

    def fake_sync(*args: object, **kwargs: object) -> None:
        called.append("kernel")

    monkeypatch.setattr(shared_proxy_addon, "handle_http_request", fake_async)
    monkeypatch.setattr(shared_proxy_addon, "handle_response", fake_async)
    monkeypatch.setattr(shared_proxy_addon, "handle_codex_websocket_message", fake_async)
    monkeypatch.setattr(shared_proxy_addon, "handle_codex_websocket_end", fake_async)
    monkeypatch.setattr(shared_proxy_addon, "log_websocket_start", fake_sync)


async def _drive_hook(addon: SharedProxyAddon, hook: str, flow: http.HTTPFlow) -> None:
    if hook == "request":
        await addon.request(flow)
        return
    if hook == "response":
        await addon.response(flow)
        return
    if hook == "websocket_start":
        addon.websocket_start(flow)
        return
    if hook == "websocket_message":
        await addon.websocket_message(flow)
        return
    if hook == "websocket_end":
        await addon.websocket_end(flow)
        return
    if hook == "error":
        await addon.error(flow)
        return
    raise AssertionError(f"unknown hook {hook}")


def _assert_fail_closed(flow: _Flow, *, websocket: bool) -> None:
    if websocket:
        assert flow.killed
        assert flow.websocket is not None
        assert flow.websocket.close_code == 1011
        return
    assert flow.response is not None
    assert flow.response.status_code == 502


async def test_http_flows_demux_pipeline_and_persistence_by_listen_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = SharedProxyBindingTable()
    metrics = SharedProxyDemuxMetrics()
    addon = SharedProxyAddon(table, metrics=metrics)
    storage_roots = _register_bindings(tmp_path, table, ("run-a", 38101), ("run-b", 38102))
    seen: list[SeenEvent] = []
    _install_recording_http_kernel(monkeypatch, seen)

    flow_a = cast("http.HTTPFlow", _Flow("flow-a", listen_port=38101))
    flow_b = cast("http.HTTPFlow", _Flow("flow-b", listen_port=38102))

    await addon.request(flow_a)
    await addon.response(flow_a)
    await addon.request(flow_b)
    await addon.response(flow_b)

    assert seen == [
        ("pipeline", "flow-a", "run-a", None, None),
        ("provisional", "flow-a", "run-a", storage_roots["run-a"], 38101),
        ("final", "flow-a", "run-a", storage_roots["run-a"], 38101),
        ("pipeline", "flow-b", "run-b", None, None),
        ("provisional", "flow-b", "run-b", storage_roots["run-b"], 38102),
        ("final", "flow-b", "run-b", storage_roots["run-b"], 38102),
    ]
    assert metrics.unmapped_flow_total == 0


async def test_responseheaders_streams_without_demux_or_finish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = SharedProxyBindingTable()
    addon = SharedProxyAddon(table)
    storage_roots = _register_bindings(tmp_path, table, ("run-a", 38101))
    seen: list[SeenEvent] = []
    _install_recording_http_kernel(monkeypatch, seen)
    flow = cast("http.HTTPFlow", _Flow("flow-a", listen_port=38101))
    flow.response = http.Response.make(200, b"", {"content-type": "text/event-stream"})
    flow.server_conn.timestamp_start = 1.0
    binding = table.snapshot().runtime_by_run_id["run-a"]

    addon.responseheaders(flow)

    assert FLOW_RUN_ID_METADATA_KEY not in flow.metadata
    assert flow.id not in binding.active_flows
    assert flow.response is not None
    assert callable(flow.response.stream)
    flow.response.raw_content = None
    stream = cast("Callable[[bytes], bytes]", flow.response.stream)
    assert stream(b"data: ping\n") == b"data: ping\n"

    await addon.request(flow)
    assert flow.id in binding.active_flows
    await addon.response(flow)

    assert flow.id not in binding.active_flows
    assert seen == [
        ("pipeline", "flow-a", "run-a", None, None),
        ("provisional", "flow-a", "run-a", storage_roots["run-a"], 38101),
        ("final", "flow-a", "run-a", storage_roots["run-a"], 38101),
    ]


async def test_interleaved_http_flows_keep_run_storage_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = SharedProxyBindingTable()
    addon = SharedProxyAddon(table)
    storage_roots = _register_bindings(tmp_path, table, ("run-a", 38101), ("run-b", 38102))
    seen: list[SeenEvent] = []
    _install_recording_http_kernel(monkeypatch, seen)
    flow_a = cast("http.HTTPFlow", _Flow("flow-a", listen_port=38101))
    flow_b = cast("http.HTTPFlow", _Flow("flow-b", listen_port=38102))

    await addon.request(flow_a)
    await addon.request(flow_b)
    await addon.response(flow_a)
    await addon.response(flow_b)

    assert seen == [
        ("pipeline", "flow-a", "run-a", None, None),
        ("provisional", "flow-a", "run-a", storage_roots["run-a"], 38101),
        ("pipeline", "flow-b", "run-b", None, None),
        ("provisional", "flow-b", "run-b", storage_roots["run-b"], 38102),
        ("final", "flow-a", "run-a", storage_roots["run-a"], 38101),
        ("final", "flow-b", "run-b", storage_roots["run-b"], 38102),
    ]


async def test_http_error_hook_uses_stamped_binding_for_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = SharedProxyBindingTable()
    addon = SharedProxyAddon(table)
    _register_bindings(tmp_path, table, ("run-a", 38101))
    deleted: list[tuple[str, str | None]] = []

    async def fake_run_pipeline(
        ir: InternalRequest,
        flow_id: str,
        run_id: str | None,
    ) -> tuple[InternalRequest, None, None]:
        return ir, None, None

    async def fake_persist_provisional(
        flow: http.HTTPFlow,
        state: RequestFlowState,
        binding: ProxyRunBinding | None = None,
    ) -> str:
        return "exchange-error"

    async def fake_delete(
        flow: http.HTTPFlow,
        state: RequestFlowState,
        binding: ProxyRunBinding | None = None,
    ) -> bool:
        deleted.append((flow.id, binding.run_id if binding is not None else None))
        return True

    monkeypatch.setattr(addon_handlers, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(
        addon_handlers,
        "persist_http_provisional_exchange",
        fake_persist_provisional,
    )
    monkeypatch.setattr(shared_proxy_addon, "delete_http_provisional_exchange", fake_delete)
    monkeypatch.setattr(bp, "is_armed", lambda: False)

    flow = cast("http.HTTPFlow", _Flow("flow-error", listen_port=38101))

    await addon.request(flow)
    await addon.error(flow)

    assert deleted == [("flow-error", "run-a")]


async def test_error_hook_clears_response_capture_without_request_state(
    tmp_path: Path,
) -> None:
    table = SharedProxyBindingTable()
    addon = SharedProxyAddon(table)
    _register_bindings(tmp_path, table, ("run-a", 38101))
    flow = cast("http.HTTPFlow", _Flow("flow-error", listen_port=38101))
    _set_demux_metadata(cast("_Flow", flow), run_id="run-a", listen_port=38101)
    flow.metadata[_STREAM_BUFFER_KEY] = bytearray(b"chunk")

    await addon.error(flow)

    assert _STREAM_BUFFER_KEY not in flow.metadata
    binding = table.snapshot().runtime_by_run_id["run-a"]
    assert flow.id not in binding.active_flows


async def test_stamped_flow_fails_closed_after_port_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = SharedProxyBindingTable()
    metrics = SharedProxyDemuxMetrics()
    addon = SharedProxyAddon(table, metrics=metrics)
    _register_bindings(tmp_path, table, ("run-old", 38101))
    table.deregister("run-old")
    _register_bindings(tmp_path, table, ("run-new", 38101))
    called: list[str] = []
    _guard_kernel(monkeypatch, called)
    fake_flow = _Flow("flow-stamped", listen_port=38101)
    _set_demux_metadata(fake_flow, run_id="run-old", listen_port=38101)
    flow = cast("http.HTTPFlow", fake_flow)

    await addon.response(flow)

    _assert_fail_closed(fake_flow, websocket=False)
    assert called == []
    assert metrics.unmapped_flow_total == 1


@pytest.mark.parametrize("missing_key", ["missing_sockname", "missing_custom_listen_port"])
async def test_request_fails_closed_when_listen_port_key_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_key: str,
) -> None:
    table = SharedProxyBindingTable()
    metrics = SharedProxyDemuxMetrics()
    addon = SharedProxyAddon(table, metrics=metrics)
    _register_bindings(tmp_path, table, ("run-a", 38101))
    called: list[str] = []
    _guard_kernel(monkeypatch, called)
    fake_flow = _Flow("flow-missing-key", listen_port=38101)
    if missing_key == "missing_sockname":
        fake_flow.client_conn.sockname = None
    else:
        fake_flow.client_conn.proxy_mode.custom_listen_port = None
    flow = cast("http.HTTPFlow", fake_flow)

    await addon.request(flow)

    _assert_fail_closed(fake_flow, websocket=False)
    assert called == []
    assert metrics.unmapped_flow_total == 1
    assert FLOW_RUN_ID_METADATA_KEY not in fake_flow.metadata
    assert FLOW_LISTEN_PORT_METADATA_KEY not in fake_flow.metadata


async def test_unmapped_http_listen_port_fails_closed_and_never_calls_kernel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = SharedProxyBindingTable()
    metrics = SharedProxyDemuxMetrics()
    addon = SharedProxyAddon(table, metrics=metrics)
    _register_bindings(tmp_path, table, ("run-a", 38101))
    called = False

    async def fake_handle_http_request(*args: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(shared_proxy_addon, "handle_http_request", fake_handle_http_request)
    flow = cast("http.HTTPFlow", _Flow("flow-unmapped", listen_port=38199))

    await addon.request(flow)

    assert flow.response is not None
    assert flow.response.status_code == 502
    assert not called
    assert metrics.unmapped_flow_total == 1
    assert FLOW_RUN_ID_METADATA_KEY not in flow.metadata


@pytest.mark.parametrize(
    ("hook", "websocket"),
    [
        ("response", False),
        ("websocket_message", True),
        ("websocket_end", True),
        ("error", False),
    ],
)
async def test_existing_hooks_fail_closed_for_unmapped_stamped_run_id(
    monkeypatch: pytest.MonkeyPatch,
    hook: str,
    websocket: bool,
) -> None:
    table = SharedProxyBindingTable()
    metrics = SharedProxyDemuxMetrics()
    addon = SharedProxyAddon(table, metrics=metrics)
    called: list[str] = []
    _guard_kernel(monkeypatch, called)
    fake_flow = _Flow(f"flow-{hook}", listen_port=38101, websocket=websocket)
    _set_demux_metadata(fake_flow, run_id="missing-run", listen_port=38101)
    flow = cast("http.HTTPFlow", fake_flow)

    await _drive_hook(addon, hook, flow)

    _assert_fail_closed(fake_flow, websocket=websocket)
    assert called == []
    assert metrics.unmapped_flow_total == 1


@pytest.mark.parametrize(
    ("hook", "websocket"),
    [
        ("response", False),
        ("websocket_message", True),
        ("websocket_end", True),
        ("error", False),
    ],
)
async def test_existing_hooks_fail_closed_for_unmapped_listen_port(
    monkeypatch: pytest.MonkeyPatch,
    hook: str,
    websocket: bool,
) -> None:
    table = SharedProxyBindingTable()
    metrics = SharedProxyDemuxMetrics()
    addon = SharedProxyAddon(table, metrics=metrics)
    called: list[str] = []
    _guard_kernel(monkeypatch, called)
    fake_flow = _Flow(f"flow-{hook}", listen_port=38199, websocket=websocket)
    _set_demux_metadata(fake_flow, listen_port=38199)
    flow = cast("http.HTTPFlow", fake_flow)

    await _drive_hook(addon, hook, flow)

    _assert_fail_closed(fake_flow, websocket=websocket)
    assert called == []
    assert metrics.unmapped_flow_total == 1


async def test_websocket_start_fails_closed_for_unmapped_listen_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = SharedProxyBindingTable()
    metrics = SharedProxyDemuxMetrics()
    addon = SharedProxyAddon(table, metrics=metrics)
    called: list[str] = []
    _guard_kernel(monkeypatch, called)
    fake_flow = _Flow("flow-websocket-start", listen_port=38199, websocket=True)
    flow = cast("http.HTTPFlow", fake_flow)

    addon.websocket_start(flow)

    _assert_fail_closed(fake_flow, websocket=True)
    assert called == []
    assert metrics.unmapped_flow_total == 1


async def test_listen_port_mismatch_fails_closed(
    tmp_path: Path,
) -> None:
    table = SharedProxyBindingTable()
    metrics = SharedProxyDemuxMetrics()
    addon = SharedProxyAddon(table, metrics=metrics)
    _register_bindings(tmp_path, table, ("run-a", 38101))
    flow = cast(
        "http.HTTPFlow",
        _Flow("flow-mismatch", listen_port=38101, custom_listen_port=38102),
    )

    await addon.request(flow)

    assert flow.response is not None
    assert flow.response.status_code == 502
    assert metrics.unmapped_flow_total == 1
    assert FLOW_RUN_ID_METADATA_KEY not in flow.metadata


async def test_websocket_flow_keeps_binding_after_mid_flow_deregister(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = SharedProxyBindingTable()
    addon = SharedProxyAddon(table)
    _register_bindings(tmp_path, table, ("run-a", 38101))
    fake_flow = _Flow("flow-ws", listen_port=38101, websocket=True)
    flow = cast("http.HTTPFlow", fake_flow)
    seen: list[tuple[str, str | None, bool]] = []
    websocket_binding: ProxyRunBinding | None = None

    async def fake_websocket_message(
        message_flow: http.HTTPFlow,
        binding: ProxyRunBinding | None = None,
    ) -> None:
        assert binding is not None
        seen.append(("message", binding.run_id, "flow-ws" in binding.active_flows))

    async def fake_websocket_end(
        message_flow: http.HTTPFlow,
        binding: ProxyRunBinding | None = None,
    ) -> None:
        nonlocal websocket_binding
        assert binding is not None
        websocket_binding = binding
        seen.append(("end", binding.run_id, "flow-ws" in binding.active_flows))

    monkeypatch.setattr(shared_proxy_addon, "log_websocket_start", lambda flow: None)
    monkeypatch.setattr(
        shared_proxy_addon,
        "handle_codex_websocket_message",
        fake_websocket_message,
    )
    monkeypatch.setattr(
        shared_proxy_addon,
        "handle_codex_websocket_end",
        fake_websocket_end,
    )

    addon.websocket_start(flow)
    table.deregister("run-a")
    await addon.websocket_message(flow)
    await addon.websocket_end(flow)

    assert seen == [("message", "run-a", True), ("end", "run-a", True)]
    assert websocket_binding is not None
    assert "flow-ws" not in websocket_binding.active_flows
    assert not fake_flow.killed


def _register_bindings(
    tmp_path: Path,
    table: SharedProxyBindingTable,
    *bindings: tuple[str, int],
) -> dict[str, str]:
    roots: dict[str, str] = {}
    for run_id, port in bindings:
        root = tmp_path / run_id
        storage = DiskStorageBackend(root)
        roots[run_id] = str(storage.root)
        table.register(
            binding_payload_from_binding(
                ProxyRunBinding(
                    run_id=run_id,
                    harness="claude",
                    working_dir=tmp_path,
                    storage=storage,
                    listen_port=port,
                    upstream="http://example.test",
                    agent_home_dir=None,
                    owned_native_session_id=None,
                    owned_source_descriptor=None,
                )
            )
        )
    return roots


def _storage_root(binding: ProxyRunBinding) -> str:
    assert isinstance(binding.storage, DiskStorageBackend)
    return str(binding.storage.root)


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
