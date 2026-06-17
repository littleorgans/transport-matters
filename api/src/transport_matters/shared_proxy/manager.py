"""API-side manager for the Tier 2 shared proxy subprocess."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import time
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from transport_matters.shared_proxy.control import SharedProxyControlClient, SharedProxyControlError
from transport_matters.shared_proxy.models import (
    DeregisterListenerRequest,
    OverrideScopePayload,
    OverrideSnapshotPayload,
    RegisterListenerRequest,
    SetOverridesRequest,
    SharedProxyBindingPayload,
    SharedProxyControlAck,
    SharedProxyControlRequest,
    binding_payload_from_binding,
)
from transport_matters.shared_proxy.process import SharedProxyProcess, SupervisorSharedProxyProcess

LOGGER = logging.getLogger(__name__)
CONTROL_SOCKET_MAX_PATH = 100

if TYPE_CHECKING:
    from collections.abc import Mapping

    from transport_matters.shared_proxy.binding import ProxyRunBinding


class SharedProxyControlChannel(Protocol):
    """Control client shape used by the manager."""

    async def ping(self) -> SharedProxyControlAck: ...

    async def request(self, request: SharedProxyControlRequest) -> SharedProxyControlAck: ...


class SharedProxyRegistryError(ValueError):
    """Invalid binding registry mutation."""


class SharedProxyProcessExited(RuntimeError):
    """Shared proxy child exited before the control channel became ready."""


OverrideScopeKey = tuple[str | None, str | None]


class SharedProxyManager:
    """Owns the API-side binding mirror and one shared proxy subprocess."""

    def __init__(
        self,
        *,
        process: SharedProxyProcess,
        control: SharedProxyControlChannel,
        ready_timeout_s: float = 5.0,
        monitor_interval_s: float | None = 0.5,
        monitor_max_backoff_s: float = 1.0,
    ) -> None:
        self._process = process
        self._control = control
        self._ready_timeout_s = ready_timeout_s
        self._monitor_interval_s = monitor_interval_s
        self._monitor_max_backoff_s = monitor_max_backoff_s
        self._by_run_id: dict[str, SharedProxyBindingPayload] = {}
        self._by_listen_port: dict[int, str] = {}
        self._overrides: dict[OverrideScopeKey, OverrideSnapshotPayload] = {}
        self._lock = asyncio.Lock()
        self._monitor_task: asyncio.Task[None] | None = None
        self._needs_rehydrate = False

    @classmethod
    def create(
        cls,
        *,
        runtime_dir: Path,
        ready_timeout_s: float = 5.0,
        request_timeout_s: float = 5.0,
        monitor_interval_s: float | None = 0.5,
        monitor_max_backoff_s: float = 1.0,
        accept_probe_timeout_s: float = 5.0,
    ) -> SharedProxyManager:
        control_socket = _control_socket_path(runtime_dir)
        process = SupervisorSharedProxyProcess(
            control_socket=control_socket,
            runtime_dir=runtime_dir,
            accept_probe_timeout_s=accept_probe_timeout_s,
        )
        control = SharedProxyControlClient(control_socket, request_timeout_s=request_timeout_s)
        return cls(
            process=process,
            control=control,
            ready_timeout_s=ready_timeout_s,
            monitor_interval_s=monitor_interval_s,
            monitor_max_backoff_s=monitor_max_backoff_s,
        )

    @property
    def by_run_id(self) -> Mapping[str, SharedProxyBindingPayload]:
        return MappingProxyType(self._by_run_id)

    @property
    def by_listen_port(self) -> Mapping[int, str]:
        return MappingProxyType(self._by_listen_port)

    @property
    def process_id(self) -> int | None:
        return self._process.process_id

    @property
    def is_running(self) -> bool:
        return self._process.is_running()

    async def start(self) -> None:
        async with self._lock:
            await self._ensure_started_locked()
        self._start_monitor()

    async def close(self) -> None:
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None
        await asyncio.to_thread(self._process.terminate)

    async def supervise(self) -> None:
        async with self._lock:
            if self._process.is_running() and not self._needs_rehydrate:
                return
            await self._ensure_started_locked()

    async def register(self, binding: ProxyRunBinding) -> None:
        payload = binding_payload_from_binding(binding)
        async with self._lock:
            self._validate_register(payload)
            await self._ensure_started_locked()
            self._by_run_id[payload.run_id] = payload
            self._by_listen_port[payload.listen_port] = payload.run_id
            try:
                await self._control.request(RegisterListenerRequest(binding=payload))
            except Exception:
                self._by_run_id.pop(payload.run_id, None)
                self._by_listen_port.pop(payload.listen_port, None)
                raise

    async def deregister(self, run_id: str) -> None:
        async with self._lock:
            payload = self._by_run_id.get(run_id)
            if payload is None:
                msg = f"run {run_id!r} is not registered with the shared proxy"
                raise SharedProxyRegistryError(msg)
            await self._ensure_started_locked()
            await self._control.request(DeregisterListenerRequest(run_id=run_id))
            self._by_run_id.pop(run_id, None)
            self._by_listen_port.pop(payload.listen_port, None)
            self._drop_overrides_for_run(run_id)

    async def set_overrides(
        self,
        scope: OverrideScopePayload,
        payload: OverrideSnapshotPayload,
    ) -> None:
        key = (scope.run_id, scope.track_id)
        async with self._lock:
            had_previous = key in self._overrides
            previous = self._overrides.get(key)
            try:
                await self._ensure_started_locked()
                await self._control.request(SetOverridesRequest(scope=scope, payload=payload))
                self._overrides[key] = payload
            except Exception:
                if had_previous and previous is not None:
                    self._overrides[key] = previous
                else:
                    self._overrides.pop(key, None)
                raise

    def _start_monitor(self) -> None:
        if self._monitor_interval_s is None or self._monitor_task is not None:
            return
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self) -> None:
        assert self._monitor_interval_s is not None
        backoff_s = self._monitor_interval_s
        while True:
            await asyncio.sleep(self._monitor_interval_s)
            try:
                await self.supervise()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("shared proxy monitor supervise attempt failed")
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, self._monitor_max_backoff_s)
            else:
                backoff_s = self._monitor_interval_s

    async def _ensure_started_locked(self) -> None:
        if not self._process.is_running():
            await asyncio.to_thread(self._process.start)
            self._needs_rehydrate = True
        await self._wait_until_ready_locked()
        if self._needs_rehydrate:
            await self._rehydrate_locked()
            self._needs_rehydrate = False

    async def _wait_until_ready_locked(self) -> None:
        deadline = time.monotonic() + self._ready_timeout_s
        last_error: SharedProxyControlError | None = None
        while time.monotonic() < deadline:
            self._raise_if_process_exited()
            try:
                await self._control.ping()
                return
            except SharedProxyControlError as exc:
                last_error = exc
            await asyncio.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        self._raise_if_process_exited()
        detail = f": {last_error.message}" if last_error is not None else ""
        msg = f"shared proxy control socket was not ready before timeout{detail}"
        raise SharedProxyControlError("control_ready_timeout", msg)

    async def _rehydrate_locked(self) -> None:
        for binding in self._by_run_id.values():
            await self._control.request(RegisterListenerRequest(binding=binding))
        for key, payload in self._overrides.items():
            scope = OverrideScopePayload(run_id=key[0], track_id=key[1])
            await self._control.request(SetOverridesRequest(scope=scope, payload=payload))

    def _validate_register(self, payload: SharedProxyBindingPayload) -> None:
        if payload.run_id in self._by_run_id:
            msg = f"run {payload.run_id!r} is already registered with the shared proxy"
            raise SharedProxyRegistryError(msg)
        existing_run_id = self._by_listen_port.get(payload.listen_port)
        if existing_run_id is not None:
            msg = (
                f"listen port {payload.listen_port} is already registered "
                f"for run {existing_run_id!r}"
            )
            raise SharedProxyRegistryError(msg)

    def _drop_overrides_for_run(self, run_id: str) -> None:
        stale_keys = [key for key in self._overrides if key[0] == run_id]
        for key in stale_keys:
            self._overrides.pop(key, None)

    def _raise_if_process_exited(self) -> None:
        exit_status = self._process.exit_status()
        if exit_status is None:
            return
        raise SharedProxyProcessExited(exit_status.message())


def _control_socket_path(runtime_dir: Path) -> Path:
    candidate = runtime_dir / "shared-proxy.sock"
    if len(str(candidate)) <= CONTROL_SOCKET_MAX_PATH:
        return candidate
    digest = hashlib.sha256(str(runtime_dir).encode()).hexdigest()[:16]
    return Path("/tmp") / f"tm-sp-{os.getpid()}-{digest}" / "s.sock"
