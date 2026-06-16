from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from mitmproxy import http

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
from transport_matters.shared_proxy.addon import (
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
        self.sockname = ("127.0.0.1", listen_port)
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
        self.websocket = _WebSocket() if websocket else None
        self.killed = False
        self.live = True

    @property
    def killable(self) -> bool:
        return True

    def kill(self) -> None:
        self.killed = True
        self.live = False


async def test_http_flows_demux_pipeline_and_persistence_by_listen_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = SharedProxyBindingTable()
    metrics = SharedProxyDemuxMetrics()
    addon = SharedProxyAddon(table, metrics=metrics)
    storage_roots = _register_bindings(tmp_path, table, ("run-a", 38101), ("run-b", 38102))
    seen: list[tuple[str, str, str | None, str | None, int | None]] = []

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
                    cli="claude",
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
