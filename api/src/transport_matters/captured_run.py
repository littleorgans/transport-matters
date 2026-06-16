"""Reusable captured-run preparation for managed agent launches."""

from __future__ import annotations

import contextlib
import os
import random
import shutil
import time
from typing import TYPE_CHECKING, Any

from transport_matters.captured_claude import build_claude_captured_invocation
from transport_matters.captured_run_context import (
    build_captured_run_context,
    persist_owned_session_facts,
    write_captured_run_manifest,
)
from transport_matters.captured_run_dependencies import (
    CapturedRunDependencies,
    default_claude_run_dependencies,
)
from transport_matters.captured_run_models import (
    CLAUDE_CLIENT_NAME,
    CLAUDE_UPSTREAM_DEFAULT,
    CODEX_CLIENT_NAME,
    WEB_RUNTIME_EMBEDDED,
    WEB_RUNTIME_EXTERNAL,
    CapturedRunBindConflict,
    CapturedRunCli,
    CapturedRunLease,
    CapturedRunProxyStartTimeout,
    CapturedRunRequest,
    CapturedRunSpawnSpec,
    CapturedRunWebRuntime,
)
from transport_matters.lock import WorkspaceLock
from transport_matters.workspace import run_root

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import datetime
    from importlib.resources.abc import Traversable

    from transport_matters.cli.launch_profile import LaunchProfile
    from transport_matters.cli.runner import (
        LaunchBindFailureOutcome,
        LaunchExitOutcome,
    )

__all__ = [
    "CLAUDE_CLIENT_NAME",
    "CLAUDE_UPSTREAM_DEFAULT",
    "CODEX_CLIENT_NAME",
    "WEB_RUNTIME_EMBEDDED",
    "WEB_RUNTIME_EXTERNAL",
    "CapturedRunBindConflict",
    "CapturedRunCli",
    "CapturedRunDependencies",
    "CapturedRunLease",
    "CapturedRunProxyStartTimeout",
    "CapturedRunRequest",
    "CapturedRunSpawnSpec",
    "CapturedRunWebRuntime",
    "build_claude_captured_invocation",
    "default_claude_run_dependencies",
    "prepare_captured_run",
    "require_web_port",
    "run_captured_run_on_local_tty",
]

_BIND_RETRY_ATTEMPTS = 3
_PROXY_TIMEOUT_RETRY_BASE_DELAY_S = 0.05
_PROXY_TIMEOUT_RETRY_JITTER_S = 0.05


def run_captured_run_on_local_tty(
    request: CapturedRunRequest,
    *,
    profile: LaunchProfile | None = None,
    print_command: bool,
    require_addon: Callable[[], Traversable],
    resolve_mitmdump: Callable[[], str | None],
    which: Callable[[str], str | None] = shutil.which,
    port_in_use: Callable[[int], bool],
    allocate_port_pair: Callable[[], tuple[int, int]],
    inject_system_prompt: Callable[..., list[str]],
    user_supplied_system_prompt: Callable[[list[str]], bool],
    validate_after_client_resolution: Callable[[], None] | None = None,
    print_banner: Callable[..., None],
    run_client_with_retry: Callable[..., None],
    env: Mapping[str, str] = os.environ,
    now: datetime | None = None,
) -> None:
    """Run the captured Claude launch on the local terminal using the shared seam."""
    from transport_matters.cli.launch_runtime import print_invocation

    ctx = build_captured_run_context(
        request,
        profile=profile,
        require_addon=require_addon,
        resolve_mitmdump=resolve_mitmdump,
        which=which,
        port_in_use=port_in_use,
        allocate_port_pair=allocate_port_pair,
        inject_system_prompt=inject_system_prompt,
        user_supplied_system_prompt=user_supplied_system_prompt,
        validate_after_client_resolution=validate_after_client_resolution,
        env=env,
        now=now,
        write=not print_command,
    )
    try:
        web_port = require_web_port(ctx.prepared.web_port)
        if print_command:
            print_invocation(
                build_invocation=ctx.build_invocation,
                proxy_port=ctx.prepared.proxy_port,
                web_port=web_port,
            )
            return

        wslock = WorkspaceLock(run_root(ctx.prepared.working_dir, ctx.prepared.run_id)).__enter__()
        try:
            persist_owned_session_facts(ctx)

            def write_manifest_for(proxy_port: int, web_port: int) -> None:
                write_captured_run_manifest(
                    ctx,
                    wslock,
                    proxy_port=proxy_port,
                    web_port=web_port,
                )

            def print_banner_for(proxy_port: int, web_port: int) -> None:
                print_banner(
                    proxy_port=proxy_port,
                    web_port=web_port,
                    upstream=request.upstream,
                    working_dir=ctx.prepared.working_dir,
                    no_claude=request.client_disabled,
                )

            run_client_with_retry(
                proxy_port=ctx.prepared.proxy_port,
                web_port=web_port,
                proxy_user_supplied=ctx.prepared.proxy_user_supplied,
                web_user_supplied=ctx.prepared.web_user_supplied,
                build_invocation=ctx.build_invocation,
                print_banner_for=print_banner_for,
                write_manifest_for=write_manifest_for,
                resolved_storage=ctx.prepared.resolved_storage,
            )
        finally:
            with contextlib.suppress(FileNotFoundError):
                wslock.manifest_path.unlink()
            wslock.__exit__(None, None, None)
    finally:
        ctx.resource_stack.close()


def prepare_captured_run(
    request: CapturedRunRequest,
    *,
    profile: LaunchProfile | None = None,
    require_addon: Callable[[], Traversable],
    resolve_mitmdump: Callable[[], str | None],
    which: Callable[[str], str | None] = shutil.which,
    port_in_use: Callable[[int], bool],
    allocate_port_pair: Callable[[], tuple[int, int]],
    inject_system_prompt: Callable[..., list[str]],
    user_supplied_system_prompt: Callable[[list[str]], bool],
    validate_after_client_resolution: Callable[[], None] | None = None,
    env: Mapping[str, str] = os.environ,
    now: datetime | None = None,
    supervisor_factory: Callable[[], Any] | None = None,
    proxy_starter: Callable[..., LaunchBindFailureOutcome | LaunchExitOutcome | None] | None = None,
    install_signal_handlers: bool = False,
    readiness_timeout_sleep: Callable[[float], None] = time.sleep,
    readiness_timeout_jitter: Callable[[], float] = random.random,
) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
    """Prepare one captured run and return the client spawn spec plus lease."""
    from transport_matters.cli.runner import (
        BindFailure,
        LaunchBindFailureOutcome,
        LaunchExitOutcome,
        handle_bind_failure,
        mitmdump_log_path,
        start_prepared_proxy,
    )
    from transport_matters.supervisor import ProcessSupervisor

    ctx = build_captured_run_context(
        request,
        profile=profile,
        require_addon=require_addon,
        resolve_mitmdump=resolve_mitmdump,
        which=which,
        port_in_use=port_in_use,
        allocate_port_pair=allocate_port_pair,
        inject_system_prompt=inject_system_prompt,
        user_supplied_system_prompt=user_supplied_system_prompt,
        validate_after_client_resolution=validate_after_client_resolution,
        env=env,
        now=now,
        write=True,
    )
    make_supervisor = supervisor_factory or ProcessSupervisor
    start_proxy = proxy_starter or start_prepared_proxy
    wslock: WorkspaceLock | None = None
    supervisor: Any | None = None
    proxy_port = ctx.prepared.proxy_port
    web_port = ctx.prepared.web_port
    last_bind_failure: BindFailure | None = None
    last_proxy_timeout: LaunchExitOutcome | None = None

    try:
        wslock = WorkspaceLock(run_root(ctx.prepared.working_dir, ctx.prepared.run_id)).__enter__()
        persist_owned_session_facts(ctx)
        for attempt in range(_BIND_RETRY_ATTEMPTS):
            write_captured_run_manifest(ctx, wslock, proxy_port=proxy_port, web_port=web_port)
            mitmdump_argv, launch_env, client = ctx.build_invocation(proxy_port, web_port)
            mitmdump_log = mitmdump_log_path(ctx.prepared.resolved_storage)
            supervisor = make_supervisor()
            if install_signal_handlers:
                supervisor.install_signal_handlers()
            outcome = start_proxy(
                sup=supervisor,
                mitmdump_argv=mitmdump_argv,
                mitmdump_env=launch_env,
                mitmdump_log=mitmdump_log,
                proxy_port=proxy_port,
                web_port=web_port,
            )
            if outcome is None:
                spawn_spec = CapturedRunSpawnSpec(
                    run_id=ctx.prepared.run_id,
                    working_dir=ctx.prepared.working_dir,
                    storage_dir=ctx.prepared.resolved_storage,
                    proxy_port=proxy_port,
                    web_port=web_port,
                    mitmdump_log=mitmdump_log,
                    client=client,
                    launch_env=launch_env,
                    managed_session=ctx.managed_session,
                    client_name=ctx.request.client_name,
                )
                lease = CapturedRunLease(
                    spawn_spec=spawn_spec,
                    _supervisor=supervisor,
                    _workspace_lock=wslock,
                    _resource_stack=ctx.resource_stack,
                )
                return spawn_spec, lease

            completed_supervisor = supervisor
            supervisor = None
            completed_supervisor.terminate_all()
            completed_supervisor.restore_signal_handlers()
            if isinstance(outcome, LaunchBindFailureOutcome):
                last_bind_failure = outcome.failure
                if attempt + 1 >= _BIND_RETRY_ATTEMPTS:
                    break
                proxy_port, web_port = handle_bind_failure(
                    outcome.failure,
                    proxy_port=proxy_port,
                    web_port=web_port,
                    proxy_user_supplied=ctx.prepared.proxy_user_supplied,
                    web_user_supplied=ctx.prepared.web_user_supplied,
                )
                continue
            if isinstance(outcome, LaunchExitOutcome):
                if _is_proxy_start_timeout(outcome):
                    last_proxy_timeout = outcome
                    if attempt + 1 >= _BIND_RETRY_ATTEMPTS:
                        break
                    readiness_timeout_sleep(
                        _proxy_timeout_retry_delay(attempt, readiness_timeout_jitter)
                    )
                    proxy_port, web_port = _reallocate_proxy_timeout_ports(
                        proxy_port=proxy_port,
                        web_port=web_port,
                        proxy_user_supplied=ctx.prepared.proxy_user_supplied,
                        web_user_supplied=ctx.prepared.web_user_supplied,
                        allocate_port_pair=allocate_port_pair,
                    )
                    continue
                _raise_prepare_outcome(outcome)

        if last_bind_failure is not None:
            raise CapturedRunBindConflict(str(last_bind_failure)) from last_bind_failure
        if last_proxy_timeout is not None:
            raise CapturedRunProxyStartTimeout(_launch_exit_message(last_proxy_timeout))
        raise RuntimeError("captured run exhausted retry attempts without an outcome")
    except Exception:
        if supervisor is not None:
            supervisor.terminate_all()
            supervisor.restore_signal_handlers()
        if wslock is not None:
            with contextlib.suppress(FileNotFoundError):
                wslock.manifest_path.unlink()
            wslock.__exit__(None, None, None)
        ctx.resource_stack.close()
        raise


def require_web_port(web_port: int | None) -> int:
    if web_port is None:
        msg = "standalone CLI captured runs require an embedded web port"
        raise ValueError(msg)
    return web_port


def _raise_prepare_outcome(outcome: LaunchBindFailureOutcome | LaunchExitOutcome) -> None:
    from transport_matters.cli.runner import LaunchBindFailureOutcome

    if isinstance(outcome, LaunchBindFailureOutcome):
        raise CapturedRunBindConflict(str(outcome.failure)) from outcome.failure
    raise RuntimeError(_launch_exit_message(outcome))


def _is_proxy_start_timeout(outcome: LaunchExitOutcome) -> bool:
    from transport_matters.cli.runner import PROXY_START_TIMEOUT_MESSAGE

    return outcome.error == PROXY_START_TIMEOUT_MESSAGE


def _proxy_timeout_retry_delay(
    attempt: int, readiness_timeout_jitter: Callable[[], float]
) -> float:
    jitter = max(0.0, min(readiness_timeout_jitter(), 1.0))
    return (_PROXY_TIMEOUT_RETRY_BASE_DELAY_S * (attempt + 1)) + (
        _PROXY_TIMEOUT_RETRY_JITTER_S * jitter
    )


def _reallocate_proxy_timeout_ports(
    *,
    proxy_port: int,
    web_port: int | None,
    proxy_user_supplied: bool,
    web_user_supplied: bool,
    allocate_port_pair: Callable[[], tuple[int, int]],
) -> tuple[int, int | None]:
    new_proxy, new_web = allocate_port_pair()
    if not proxy_user_supplied:
        proxy_port = new_proxy
    if web_port is not None and not web_user_supplied:
        web_port = new_web
    return proxy_port, web_port


def _launch_exit_message(outcome: LaunchExitOutcome) -> str:
    return outcome.error or f"captured run exited during prepare (code {outcome.exit_code})"
