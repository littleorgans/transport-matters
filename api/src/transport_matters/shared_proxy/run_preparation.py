"""Prepare API managed captured runs for the shared proxy subprocess."""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from transport_matters.captured_run_context import (
    CapturedRunContext,
    build_captured_run_context,
    persist_owned_session_facts,
    write_captured_run_manifest,
)
from transport_matters.captured_run_models import (
    CapturedRunBindConflict,
    CapturedRunProxyStartTimeout,
    CapturedRunRequest,
    CapturedRunSpawnSpec,
)
from transport_matters.cli.runner import mitmdump_log_path
from transport_matters.lock import WorkspaceLock
from transport_matters.shared_proxy.binding import ProxyRunBinding
from transport_matters.shared_proxy.control import SharedProxyControlError
from transport_matters.shared_proxy.manager import SharedProxyManager, SharedProxyRegistryError
from transport_matters.storage.disk import DiskStorageBackend
from transport_matters.workspace import run_root

if TYPE_CHECKING:
    from contextlib import ExitStack
    from pathlib import Path

    from transport_matters.captured_run_dependencies import CapturedRunDependencies


_TIMEOUT_CONTROL_CODES = frozenset(
    {
        "control_connect_timeout",
        "control_ready_timeout",
        "control_request_timeout",
        "listener_ready_timeout",
    }
)


@dataclass(slots=True)
class SharedCapturedRunLease:
    spawn_spec: CapturedRunSpawnSpec
    _shared_proxy: SharedProxyManager
    _workspace_lock: WorkspaceLock
    _resource_stack: ExitStack
    _closed: bool = False

    async def aclose(self) -> None:
        """Idempotently deregister the shared proxy binding and release local resources."""
        if self._closed:
            return
        self._closed = True
        try:
            await self._shared_proxy.deregister(self.spawn_spec.run_id)
        finally:
            with contextlib.suppress(FileNotFoundError):
                self._workspace_lock.manifest_path.unlink()
            self._workspace_lock.__exit__(None, None, None)
            self._resource_stack.close()

    def close(self) -> None:
        """Sync compatibility for callers that still close leases from a worker thread."""
        asyncio.run(self.aclose())


async def prepare_shared_captured_run(
    request: CapturedRunRequest,
    *,
    shared_proxy: SharedProxyManager,
    dependencies: CapturedRunDependencies,
) -> tuple[CapturedRunSpawnSpec, SharedCapturedRunLease]:
    """Prepare a Context B captured run without starting a per run mitmdump."""

    ctx = await asyncio.to_thread(
        build_captured_run_context,
        request,
        profile=None,
        require_addon=dependencies.require_addon,
        resolve_mitmdump=dependencies.resolve_mitmdump,
        which=dependencies.which,
        port_in_use=dependencies.port_in_use,
        allocate_port_pair=dependencies.allocate_port_pair,
        inject_system_prompt=dependencies.inject_system_prompt,
        user_supplied_system_prompt=dependencies.user_supplied_system_prompt,
        validate_after_client_resolution=None,
        env=os.environ,
        now=None,
        write=True,
    )
    return await _finish_shared_preparation(ctx, shared_proxy=shared_proxy)


async def _finish_shared_preparation(
    ctx: CapturedRunContext,
    *,
    shared_proxy: SharedProxyManager,
) -> tuple[CapturedRunSpawnSpec, SharedCapturedRunLease]:
    wslock: WorkspaceLock | None = None
    registered = False
    proxy_port = ctx.prepared.proxy_port
    web_port = ctx.prepared.web_port
    try:
        wslock = WorkspaceLock(run_root(ctx.prepared.working_dir, ctx.prepared.run_id)).__enter__()
        persist_owned_session_facts(ctx)
        write_captured_run_manifest(ctx, wslock, proxy_port=proxy_port, web_port=web_port)
        _mitmdump_argv, launch_env, client = ctx.build_invocation(proxy_port, web_port)
        _require_owned_session(ctx)
        binding = _binding_from_context(ctx, proxy_port=proxy_port)
        try:
            await shared_proxy.register(binding)
        except SharedProxyRegistryError as exc:
            raise CapturedRunBindConflict(str(exc)) from exc
        except SharedProxyControlError as exc:
            _raise_control_error(exc)
        registered = True
        spawn_spec = CapturedRunSpawnSpec(
            run_id=ctx.prepared.run_id,
            working_dir=ctx.prepared.working_dir,
            storage_dir=ctx.prepared.resolved_storage,
            proxy_port=proxy_port,
            web_port=web_port,
            mitmdump_log=mitmdump_log_path(ctx.prepared.resolved_storage),
            client=client,
            launch_env=launch_env,
            managed_session=ctx.managed_session,
            client_name=ctx.request.client_name,
        )
        return spawn_spec, SharedCapturedRunLease(
            spawn_spec=spawn_spec,
            _shared_proxy=shared_proxy,
            _workspace_lock=wslock,
            _resource_stack=ctx.resource_stack,
        )
    except Exception:
        if registered:
            with contextlib.suppress(Exception):
                await shared_proxy.deregister(ctx.prepared.run_id)
        if wslock is not None:
            with contextlib.suppress(FileNotFoundError):
                wslock.manifest_path.unlink()
            wslock.__exit__(None, None, None)
        ctx.resource_stack.close()
        raise


def _binding_from_context(ctx: CapturedRunContext, *, proxy_port: int) -> ProxyRunBinding:
    return ProxyRunBinding(
        run_id=ctx.prepared.run_id,
        cli=ctx.request.client_name,
        working_dir=ctx.prepared.working_dir,
        storage=DiskStorageBackend(ctx.prepared.resolved_storage),
        listen_port=proxy_port,
        upstream=ctx.request.upstream,
        agent_home_dir=_descriptor_home(ctx),
        owned_native_session_id=(
            ctx.managed_session.native_session_id if ctx.managed_session is not None else None
        ),
        owned_source_descriptor=(
            ctx.managed_session.source_descriptor if ctx.managed_session is not None else None
        ),
        launch_fields=MappingProxyType(_launch_fields(ctx)),
        default_client_passthrough=tuple(ctx.request.default_client_passthrough),
    )


def _require_owned_session(ctx: CapturedRunContext) -> None:
    if (
        ctx.managed_session is not None
        and ctx.managed_session.native_session_id is not None
        and ctx.managed_session.source_descriptor is not None
    ):
        return
    msg = "shared captured run requires launcher owned transcript metadata"
    raise RuntimeError(msg)


def _descriptor_home(ctx: CapturedRunContext) -> Path | None:
    if ctx.runtime_home_plan is None:
        return None
    return ctx.runtime_home_plan.descriptor_home


def _launch_fields(ctx: CapturedRunContext) -> dict[str, object]:
    launch_fields = dict(ctx.request.launch_fields)
    if ctx.runtime_home_plan is not None:
        launch_fields.update(ctx.runtime_home_plan.launch_fields)
    return launch_fields


def _raise_control_error(exc: SharedProxyControlError) -> None:
    if exc.code in _TIMEOUT_CONTROL_CODES:
        raise CapturedRunProxyStartTimeout(exc.message) from exc
    raise exc
