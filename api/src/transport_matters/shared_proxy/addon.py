from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, cast

from mitmproxy import exceptions, http

from transport_matters.addon_handlers import (
    handle_codex_websocket_end,
    handle_codex_websocket_message,
    handle_http_request,
    handle_response,
    handle_response_headers,
    log_websocket_start,
)
from transport_matters.codex.transport import is_codex_http_responses_flow, is_codex_websocket_flow
from transport_matters.exchange_recorder import delete_http_provisional_exchange
from transport_matters.flow_state import get_request_flow_state
from transport_matters.response_stream import clear_response_capture
from transport_matters.shared_proxy.binding import ProxyRunBinding
from transport_matters.storage.disk import DiskStorageBackend

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from transport_matters.counting import TokenCountingClient
    from transport_matters.shared_proxy.models import SharedProxyBindingPayload

LOGGER = logging.getLogger(__name__)

FLOW_RUN_ID_METADATA_KEY = "transport_matters_shared_proxy_run_id"
FLOW_LISTEN_PORT_METADATA_KEY = "transport_matters_shared_proxy_listen_port"

DemuxFailureReason = Literal[
    "missing_sockname",
    "missing_custom_listen_port",
    "listen_port_mismatch",
    "unmapped_listen_port",
    "unmapped_run_id",
]


@dataclass(frozen=True, slots=True)
class DemuxFailure:
    reason: DemuxFailureReason
    listen_port: int | None


@dataclass(slots=True)
class SharedProxyDemuxMetrics:
    unmapped_flow_total: int = 0

    def increment_unmapped_flow(self) -> None:
        self.unmapped_flow_total += 1


@dataclass(frozen=True, slots=True)
class BindingTableSnapshot:
    by_run_id: Mapping[str, SharedProxyBindingPayload]
    by_listen_port: Mapping[int, str]
    runtime_by_run_id: Mapping[str, ProxyRunBinding]


class SharedProxyBindingTable:
    """Subprocess-side binding table shared by the control channel and addon."""

    def __init__(self) -> None:
        self._payload_by_run_id: dict[str, SharedProxyBindingPayload] = {}
        self._run_id_by_listen_port: dict[int, str] = {}
        self._runtime_by_run_id: dict[str, ProxyRunBinding] = {}
        self._runtime_by_flow_id: dict[str, ProxyRunBinding] = {}

    @property
    def by_run_id(self) -> Mapping[str, SharedProxyBindingPayload]:
        return MappingProxyType(self._payload_by_run_id)

    @property
    def by_listen_port(self) -> Mapping[int, str]:
        return MappingProxyType(self._run_id_by_listen_port)

    def snapshot(self) -> BindingTableSnapshot:
        return BindingTableSnapshot(
            by_run_id=MappingProxyType(dict(self._payload_by_run_id)),
            by_listen_port=MappingProxyType(dict(self._run_id_by_listen_port)),
            runtime_by_run_id=MappingProxyType(dict(self._runtime_by_run_id)),
        )

    def restore(self, snapshot: BindingTableSnapshot) -> None:
        self._payload_by_run_id = dict(snapshot.by_run_id)
        self._run_id_by_listen_port = dict(snapshot.by_listen_port)
        self._runtime_by_run_id = dict(snapshot.runtime_by_run_id)
        self._runtime_by_flow_id = {
            flow_id: binding
            for flow_id, binding in self._runtime_by_flow_id.items()
            if binding.run_id in self._runtime_by_run_id
        }

    def register(self, payload: SharedProxyBindingPayload) -> ProxyRunBinding:
        binding = _runtime_binding_from_payload(payload)
        self._payload_by_run_id[payload.run_id] = payload
        self._run_id_by_listen_port[payload.listen_port] = payload.run_id
        self._runtime_by_run_id[payload.run_id] = binding
        return binding

    def deregister(self, run_id: str) -> SharedProxyBindingPayload | None:
        payload = self._payload_by_run_id.pop(run_id, None)
        if payload is None:
            return None
        self._run_id_by_listen_port.pop(payload.listen_port, None)
        self._runtime_by_run_id.pop(run_id, None)
        return payload

    def mode_specs(self) -> list[str]:
        return [payload.mode_spec() for payload in self._payload_by_run_id.values()]

    def resolve_new_flow(self, *, flow_id: str, listen_port: int) -> ProxyRunBinding | None:
        run_id = self._run_id_by_listen_port.get(listen_port)
        if run_id is None:
            return None
        binding = self._runtime_by_run_id.get(run_id)
        if binding is None:
            return None
        self._runtime_by_flow_id[flow_id] = binding
        binding.active_flows.add(flow_id)
        return binding

    def resolve_existing_flow(
        self,
        *,
        flow_id: str,
        run_id: str | None,
        listen_port: int | None,
    ) -> ProxyRunBinding | None:
        binding = self._runtime_by_flow_id.get(flow_id)
        if binding is not None and (run_id is None or binding.run_id == run_id):
            return binding
        if run_id is not None:
            binding = self._runtime_by_run_id.get(run_id)
            if binding is not None:
                self._runtime_by_flow_id[flow_id] = binding
                binding.active_flows.add(flow_id)
                return binding
            return None
        if listen_port is None:
            return None
        return self.resolve_new_flow(flow_id=flow_id, listen_port=listen_port)

    def finish_flow(self, flow_id: str) -> None:
        binding = self._runtime_by_flow_id.pop(flow_id, None)
        if binding is not None:
            binding.active_flows.discard(flow_id)


class SharedProxyAddon:
    """Mitmproxy addon that demuxes flows to per-run bindings."""

    def __init__(
        self,
        bindings: SharedProxyBindingTable,
        *,
        token_counter: TokenCountingClient | None = None,
        metrics: SharedProxyDemuxMetrics | None = None,
    ) -> None:
        self._bindings = bindings
        self._token_counter = token_counter
        self.metrics = metrics or SharedProxyDemuxMetrics()

    async def request(self, flow: http.HTTPFlow) -> None:
        binding = self._resolve_new_flow(flow)
        if binding is None:
            self._fail_http(flow)
            return
        await handle_http_request(flow, self._token_counter, binding)

    def websocket_start(self, flow: http.HTTPFlow) -> None:
        binding = self._resolve_new_flow(flow)
        if binding is None:
            self._kill_websocket(flow)
            return
        log_websocket_start(flow)

    async def websocket_message(self, flow: http.HTTPFlow) -> None:
        binding = self._resolve_existing_flow(flow)
        if binding is None:
            self._kill_websocket(flow)
            return
        await handle_codex_websocket_message(flow, binding)

    async def websocket_end(self, flow: http.HTTPFlow) -> None:
        binding = self._resolve_existing_flow(flow)
        if binding is None:
            self._kill_websocket(flow)
            return
        try:
            await handle_codex_websocket_end(flow, binding)
        finally:
            self._bindings.finish_flow(flow.id)

    async def response(self, flow: http.HTTPFlow) -> None:
        binding = self._resolve_existing_flow(flow)
        if binding is None:
            self._fail_http(flow)
            return
        try:
            await handle_response(flow, self._token_counter, binding)
        finally:
            self._bindings.finish_flow(flow.id)

    def responseheaders(self, flow: http.HTTPFlow) -> None:
        handle_response_headers(flow)

    async def error(self, flow: http.HTTPFlow) -> None:
        binding: ProxyRunBinding | None = None
        try:
            binding = self._resolve_existing_flow(flow)
            if binding is None:
                self._fail_http(flow)
                return
            if is_codex_websocket_flow(flow) and not is_codex_http_responses_flow(flow):
                return
            request_state = get_request_flow_state(flow)
            if request_state is None or request_state.provisional_exchange_id is None:
                return
            await delete_http_provisional_exchange(flow, request_state, binding)
        finally:
            if binding is not None:
                self._bindings.finish_flow(flow.id)
            clear_response_capture(flow)

    def _resolve_new_flow(self, flow: http.HTTPFlow) -> ProxyRunBinding | None:
        result = _flow_listen_port(flow)
        if isinstance(result, DemuxFailure):
            self._record_unmapped(flow, result)
            return None
        binding = self._bindings.resolve_new_flow(flow_id=flow.id, listen_port=result)
        if binding is None:
            self._record_unmapped(flow, DemuxFailure("unmapped_listen_port", result))
            return None
        _stamp_flow(flow, binding)
        return binding

    def _resolve_existing_flow(self, flow: http.HTTPFlow) -> ProxyRunBinding | None:
        run_id = _metadata_str(flow, FLOW_RUN_ID_METADATA_KEY)
        listen_port = _metadata_int(flow, FLOW_LISTEN_PORT_METADATA_KEY)
        binding = self._bindings.resolve_existing_flow(
            flow_id=flow.id,
            run_id=run_id,
            listen_port=listen_port,
        )
        if binding is None:
            self._record_unmapped(flow, DemuxFailure("unmapped_run_id", listen_port))
            return None
        _stamp_flow(flow, binding)
        return binding

    def _record_unmapped(self, flow: http.HTTPFlow, failure: DemuxFailure) -> None:
        self.metrics.increment_unmapped_flow()
        LOGGER.warning(
            "shared proxy unmapped flow id=%s listen_port=%s reason=%s",
            flow.id,
            failure.listen_port,
            failure.reason,
        )

    def _fail_http(self, flow: http.HTTPFlow) -> None:
        flow.response = http.Response.make(
            502,
            b"shared proxy could not map flow to run",
            {"content-type": "text/plain"},
        )

    def _kill_websocket(self, flow: http.HTTPFlow) -> None:
        websocket = getattr(flow, "websocket", None)
        if websocket is not None:
            websocket.closed_by_client = False
            websocket.close_code = 1011
            websocket.close_reason = "shared proxy could not map flow to run"
            websocket.timestamp_end = time.time()
        with contextlib.suppress(exceptions.ControlException):
            cast("Callable[[], None]", flow.kill)()


def _runtime_binding_from_payload(payload: SharedProxyBindingPayload) -> ProxyRunBinding:
    if payload.storage_root is None:
        msg = f"shared proxy binding {payload.run_id!r} is missing storage root"
        raise ValueError(msg)
    return ProxyRunBinding(
        run_id=payload.run_id,
        harness=payload.harness,
        working_dir=_optional_path(payload.working_dir),
        storage=DiskStorageBackend(payload.storage_root),
        listen_port=payload.listen_port,
        upstream=payload.upstream,
        agent_home_dir=_optional_path(payload.agent_home_dir),
        owned_native_session_id=payload.owned_native_session_id,
        owned_source_descriptor=payload.owned_source_descriptor,
        space_id=payload.space_id,
        worktree_id=payload.worktree_id,
        launch_fields=MappingProxyType(dict(payload.launch_fields)),
        default_client_passthrough=tuple(payload.default_client_passthrough),
        breakpoint_skip_models=tuple(payload.breakpoint_skip_models),
    )


def _flow_listen_port(flow: http.HTTPFlow) -> int | DemuxFailure:
    sock_port = _sockname_port(flow)
    if sock_port is None:
        return DemuxFailure("missing_sockname", None)
    mode_port = _custom_listen_port(flow)
    if mode_port is None:
        return DemuxFailure("missing_custom_listen_port", sock_port)
    if mode_port != sock_port:
        return DemuxFailure("listen_port_mismatch", sock_port)
    return sock_port


def _sockname_port(flow: http.HTTPFlow) -> int | None:
    client_conn = getattr(flow, "client_conn", None)
    sockname = getattr(client_conn, "sockname", None)
    if not isinstance(sockname, tuple) or len(sockname) < 2:
        return None
    port = sockname[1]
    return port if isinstance(port, int) else None


def _custom_listen_port(flow: http.HTTPFlow) -> int | None:
    client_conn = getattr(flow, "client_conn", None)
    proxy_mode = getattr(client_conn, "proxy_mode", None)
    port = getattr(proxy_mode, "custom_listen_port", None)
    return port if isinstance(port, int) else None


def _stamp_flow(flow: http.HTTPFlow, binding: ProxyRunBinding) -> None:
    flow.metadata[FLOW_RUN_ID_METADATA_KEY] = binding.run_id
    flow.metadata[FLOW_LISTEN_PORT_METADATA_KEY] = binding.listen_port


def _metadata_str(flow: http.HTTPFlow, key: str) -> str | None:
    value = flow.metadata.get(key)
    return value if isinstance(value, str) else None


def _metadata_int(flow: http.HTTPFlow, key: str) -> int | None:
    value = flow.metadata.get(key)
    return value if isinstance(value, int) else None


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value is not None else None
