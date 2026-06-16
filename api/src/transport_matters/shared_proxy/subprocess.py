"""Shared mitmproxy subprocess entrypoint for Tier 2 Slice 5."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from transport_matters.override_state import get_store, scope_from_params
from transport_matters.shared_proxy.addon import SharedProxyAddon, SharedProxyBindingTable
from transport_matters.shared_proxy.control import SharedProxyControlError, SharedProxyControlServer
from transport_matters.shared_proxy.models import (
    DeregisterListenerRequest,
    OverrideScopePayload,
    OverrideSnapshotPayload,
    PingRequest,
    RegisterListenerRequest,
    SetOverridesRequest,
    SharedProxyBindingPayload,
    SharedProxyControlAck,
    SharedProxyControlRequest,
)

if TYPE_CHECKING:
    from collections.abc import Callable

LOGGER = logging.getLogger(__name__)


class SharedProxySubprocess:
    """Owns DumpMaster, listener modes, and the subprocess-side binding table."""

    def __init__(self, *, control_socket: Path, accept_probe_timeout_s: float = 5.0) -> None:
        self.control_socket = control_socket
        self.accept_probe_timeout_s = accept_probe_timeout_s
        self._bindings = SharedProxyBindingTable()
        self._master: DumpMaster | None = None
        self._server = SharedProxyControlServer(control_socket, self.handle_request)
        self.proxy_generation = 0
        self.mode_generation = 0
        self.overrides_generation = 0

    async def run(self) -> None:
        options = Options(listen_host="127.0.0.1", mode=[])
        self._master = DumpMaster(
            options,
            loop=asyncio.get_running_loop(),
            with_termlog=False,
            with_dumper=False,
        )
        cast("Callable[[object], None]", self._master.addons.add)(SharedProxyAddon(self._bindings))
        master_task = asyncio.create_task(self._master.run())
        await self._server.start()
        try:
            await master_task
        finally:
            await self._server.close()
            master_any = cast("Any", self._master)  # Any: mitmproxy shutdown is untyped.
            master_any.shutdown()
            with contextlib.suppress(Exception):
                await master_task

    async def handle_request(self, request: SharedProxyControlRequest) -> SharedProxyControlAck:
        if isinstance(request, PingRequest):
            return self._ack()
        if isinstance(request, RegisterListenerRequest):
            await self.register_listener(request.binding)
            return self._ack()
        if isinstance(request, DeregisterListenerRequest):
            await self.deregister_listener(request.run_id)
            return self._ack()
        if isinstance(request, SetOverridesRequest):
            self.set_overrides(request.scope, request.payload)
            return self._ack()
        raise AssertionError("unknown shared proxy control request")

    async def register_listener(self, binding: SharedProxyBindingPayload) -> None:
        self._validate_register(binding)
        previous_bindings = self._bindings.snapshot()
        self._bindings.register(binding)
        try:
            self._apply_modes()
            await wait_for_tcp_accept(
                "127.0.0.1",
                binding.listen_port,
                should_accept=True,
                timeout_s=self.accept_probe_timeout_s,
            )
        except Exception as exc:
            self._bindings.restore(previous_bindings)
            self._apply_modes()
            msg = f"listener {binding.listen_port} failed readiness probe"
            raise SharedProxyControlError("listener_ready_timeout", msg) from exc
        self.mode_generation += 1

    async def deregister_listener(self, run_id: str) -> None:
        binding = self._bindings.by_run_id.get(run_id)
        if binding is None:
            return
        previous_bindings = self._bindings.snapshot()
        self._bindings.deregister(run_id)
        try:
            self._apply_modes()
            await wait_for_tcp_accept(
                "127.0.0.1",
                binding.listen_port,
                should_accept=False,
                timeout_s=self.accept_probe_timeout_s,
            )
        except Exception as exc:
            self._bindings.restore(previous_bindings)
            self._apply_modes()
            msg = f"listener {binding.listen_port} failed close probe"
            raise SharedProxyControlError("listener_close_timeout", msg) from exc
        self.mode_generation += 1

    def set_overrides(
        self,
        scope: OverrideScopePayload,
        payload: OverrideSnapshotPayload,
    ) -> None:
        store = get_store()
        override_scope = scope_from_params(scope.run_id, scope.track_id)
        store.clear(scope=override_scope)
        for override in payload.overrides:
            store.upsert(override, scope=override_scope)
        store.set_enabled(payload.enabled, scope=override_scope)
        self.overrides_generation += 1

    def _validate_register(self, binding: SharedProxyBindingPayload) -> None:
        existing = self._bindings.by_run_id.get(binding.run_id)
        if existing is not None and existing.listen_port != binding.listen_port:
            msg = f"run {binding.run_id!r} is already registered on another listener"
            raise SharedProxyControlError("duplicate_run_id", msg)
        existing_run_id = self._bindings.by_listen_port.get(binding.listen_port)
        existing_port = (
            self._bindings.by_run_id.get(existing_run_id) if existing_run_id is not None else None
        )
        if existing_port is not None and existing_port.run_id != binding.run_id:
            msg = f"listen port {binding.listen_port} is already registered"
            raise SharedProxyControlError("duplicate_listen_port", msg)
        if binding.mode_kind == "reverse" and binding.upstream is None:
            msg = "reverse listener registration requires an upstream"
            raise SharedProxyControlError("missing_upstream", msg)

    def _apply_modes(self) -> None:
        if self._master is None:
            msg = "mitmproxy master is not running"
            raise SharedProxyControlError("master_not_running", msg)
        modes = self._bindings.mode_specs()
        options_any = cast("Any", self._master.options)  # Any: mitmproxy options.update is untyped.
        options_any.update(mode=modes)

    def _ack(self) -> SharedProxyControlAck:
        return SharedProxyControlAck(
            proxyGeneration=self.proxy_generation,
            modeGeneration=self.mode_generation,
            overridesGeneration=self.overrides_generation,
        )


async def wait_for_tcp_accept(
    host: str,
    port: int,
    *,
    should_accept: bool,
    timeout_s: float,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        accepted = await _tcp_connects(host, port)
        if accepted is should_accept:
            return
        await asyncio.sleep(0.05)
    state = "accept connections" if should_accept else "refuse connections"
    msg = f"127.0.0.1:{port} did not {state} before timeout"
    raise TimeoutError(msg)


async def _tcp_connects(host: str, port: int) -> bool:
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=0.25,
        )
    except OSError:
        return False
    except TimeoutError:
        return False
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the shared Transport Matters proxy")
    parser.add_argument("--control-socket", required=True, type=Path)
    parser.add_argument("--accept-probe-timeout-s", type=float, default=5.0)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    proxy = SharedProxySubprocess(
        control_socket=args.control_socket,
        accept_probe_timeout_s=args.accept_probe_timeout_s,
    )
    await proxy.run()
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
