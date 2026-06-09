"""Reusable captured-run preparation for managed agent launches."""

from __future__ import annotations

import contextlib
import os
import shutil
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import as_file
from typing import TYPE_CHECKING, Any

from transport_matters.lock import WorkspaceLock
from transport_matters.workspace import run_root

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from importlib.resources.abc import Traversable
    from pathlib import Path

    from transport_matters.cli.launch_profile import LaunchProfile, ManagedSession
    from transport_matters.cli.runner import (
        LaunchBindFailureOutcome,
        LaunchExitOutcome,
        ManagedClient,
    )

_BIND_RETRY_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class CapturedRunRequest:
    client_name: str
    passthrough: tuple[str, ...]
    directory: Path | None
    proxy_port: int | None
    web_port: int | None
    upstream: str
    storage_dir: Path | None
    home_dir: Path | None
    client_bin: Path | None
    client_disabled: bool
    no_system_prompt: bool
    debug: bool


@dataclass(frozen=True, slots=True)
class CapturedRunSpawnSpec:
    run_id: str
    working_dir: Path
    storage_dir: Path
    proxy_port: int
    web_port: int
    mitmdump_log: Path
    client: ManagedClient | None
    launch_env: dict[str, str]
    managed_session: ManagedSession | None


@dataclass(slots=True)
class CapturedRunLease:
    spawn_spec: CapturedRunSpawnSpec
    _supervisor: Any
    _workspace_lock: WorkspaceLock
    _resource_stack: ExitStack
    _closed: bool = False

    def close(self) -> None:
        """Idempotently release every resource owned by this captured run."""
        if self._closed:
            return
        self._closed = True
        self._supervisor.terminate_all()
        self._supervisor.restore_signal_handlers()
        with contextlib.suppress(FileNotFoundError):
            self._workspace_lock.manifest_path.unlink()
        self._workspace_lock.__exit__(None, None, None)
        self._resource_stack.close()


@dataclass(slots=True)
class _CapturedRunContext:
    request: CapturedRunRequest
    profile: Any
    prepared: Any
    managed_session: Any | None
    build_invocation: Callable[[int, int], tuple[list[str], dict[str, str], Any | None]]
    resource_stack: ExitStack


def build_start_invocation(
    *,
    addon_path: Path,
    mitmdump: str,
    upstream: str,
    working_dir: Path,
    resolved_storage: Path,
    run_id: str,
    home_dir: Path | None,
    claude_path: str | None,
    claude_passthrough_user: Sequence[str],
    no_claude: bool,
    no_system_prompt: bool,
    debug: bool,
    profile: LaunchProfile,
    managed_session: ManagedSession | None,
    inject_system_prompt: Callable[..., list[str]],
    user_supplied_system_prompt: Callable[[list[str]], bool],
) -> Callable[[int, int], tuple[list[str], dict[str, str], ManagedClient | None]]:
    """Build the retry-safe invocation factory for a captured Claude launch."""
    from transport_matters.cli.launch_runtime import (
        CLIENT_NAME_CLAUDE,
        build_launch_env,
        build_managed_child_env,
        build_mitmdump_argv,
    )
    from transport_matters.cli.net import loopback_http_url
    from transport_matters.cli.runner import ManagedClient

    def build_invocation(
        proxy_port: int,
        web_port: int,
    ) -> tuple[list[str], dict[str, str], ManagedClient | None]:
        passthrough = list(claude_passthrough_user)
        if not no_claude and not no_system_prompt and not user_supplied_system_prompt(passthrough):
            passthrough = inject_system_prompt(
                passthrough,
                proxy_port=proxy_port,
                web_port=web_port,
            )

        native_session_id = (
            managed_session.native_session_id if managed_session is not None else None
        )
        env = build_launch_env(
            working_dir=working_dir,
            storage_dir=resolved_storage,
            proxy_port=proxy_port,
            web_port=web_port,
            run_id=run_id,
            cli=CLIENT_NAME_CLAUDE,
            home_dir=home_dir,
            owned_native_session_id=native_session_id,
            owned_source_descriptor=(
                managed_session.source_descriptor if managed_session is not None else None
            ),
        )
        argv = build_mitmdump_argv(
            mitmdump=mitmdump,
            mode=f"reverse:{upstream}",
            proxy_port=proxy_port,
            addon_path=addon_path,
            debug=debug,
        )

        client = None
        if claude_path is not None:
            client_env = build_managed_child_env(
                env,
                client_name=CLIENT_NAME_CLAUDE,
                home_dir=home_dir,
                extra_env={"ANTHROPIC_BASE_URL": loopback_http_url(proxy_port)},
            )
            client = ManagedClient(
                name=CLIENT_NAME_CLAUDE,
                display_name="Claude",
                argv=profile.client_argv(
                    client_path=claude_path,
                    passthrough=passthrough,
                    native_session_id=native_session_id,
                ),
                env=client_env,
                cwd=working_dir,
            )
        return argv, env, client

    return build_invocation


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
    from transport_matters.cli.home_seed import seed_home_dir
    from transport_matters.cli.launch_runtime import CLIENT_NAME_CLAUDE, print_invocation

    ctx = _build_captured_run_context(
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
        if print_command:
            print_invocation(
                build_invocation=ctx.build_invocation,
                proxy_port=ctx.prepared.proxy_port,
                web_port=ctx.prepared.web_port,
            )
            return

        if request.home_dir is not None and ctx.prepared.client_path is not None:
            seed_home_dir(
                CLIENT_NAME_CLAUDE,
                home_dir=request.home_dir,
                working_dir=ctx.prepared.working_dir,
            )

        wslock = WorkspaceLock(run_root(ctx.prepared.working_dir, ctx.prepared.run_id)).__enter__()
        try:
            _persist_owned_session_facts(ctx)

            def write_manifest_for(proxy_port: int, web_port: int) -> None:
                _write_workspace_manifest(ctx, wslock, proxy_port=proxy_port, web_port=web_port)

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
                web_port=ctx.prepared.web_port,
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

    ctx = _build_captured_run_context(
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

    try:
        wslock = WorkspaceLock(run_root(ctx.prepared.working_dir, ctx.prepared.run_id)).__enter__()
        _persist_owned_session_facts(ctx)
        for attempt in range(_BIND_RETRY_ATTEMPTS):
            _write_workspace_manifest(ctx, wslock, proxy_port=proxy_port, web_port=web_port)
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
                _raise_prepare_outcome(outcome)

        if last_bind_failure is not None:
            raise last_bind_failure
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


def _build_captured_run_context(
    request: CapturedRunRequest,
    *,
    profile: LaunchProfile | None,
    require_addon: Callable[[], Traversable],
    resolve_mitmdump: Callable[[], str | None],
    which: Callable[[str], str | None],
    port_in_use: Callable[[int], bool],
    allocate_port_pair: Callable[[], tuple[int, int]],
    inject_system_prompt: Callable[..., list[str]],
    user_supplied_system_prompt: Callable[[list[str]], bool],
    validate_after_client_resolution: Callable[[], None] | None,
    env: Mapping[str, str],
    now: datetime | None,
    write: bool,
) -> _CapturedRunContext:
    from transport_matters.cli.launch_profile import ClaudeLaunchProfile, prepare_managed_session
    from transport_matters.cli.launch_runtime import CLIENT_NAME_CLAUDE, prepare_launch

    if request.client_name != CLIENT_NAME_CLAUDE:
        raise ValueError(f"unsupported captured client: {request.client_name!r}")
    launch_profile = profile or ClaudeLaunchProfile()
    prepared = prepare_launch(
        passthrough=list(request.passthrough),
        directory=request.directory,
        proxy_port=request.proxy_port,
        web_port=request.web_port,
        storage_dir=request.storage_dir,
        client_name=request.client_name,
        bin_override=request.client_bin,
        client_disabled=request.client_disabled,
        not_found_hint=_claude_not_found_hint(),
        require_addon=require_addon,
        resolve_mitmdump=resolve_mitmdump,
        which=which,
        port_in_use=port_in_use,
        allocate_port_pair=allocate_port_pair,
        validate_after_client_resolution=validate_after_client_resolution,
    )
    managed_session = prepare_managed_session(
        launch_profile,
        client_path=prepared.client_path,
        passthrough=prepared.passthrough_user,
        working_dir=prepared.working_dir,
        home_dir=request.home_dir,
        env=env,
        now=now or datetime.now().astimezone(),
        write=write,
    )
    stack = ExitStack()
    try:
        addon_path = stack.enter_context(as_file(prepared.addon_traversable))
        build_invocation = build_start_invocation(
            addon_path=addon_path,
            mitmdump=prepared.mitmdump,
            upstream=request.upstream,
            working_dir=prepared.working_dir,
            resolved_storage=prepared.resolved_storage,
            run_id=prepared.run_id,
            home_dir=request.home_dir,
            claude_path=prepared.client_path,
            claude_passthrough_user=prepared.passthrough_user,
            no_claude=request.client_disabled,
            no_system_prompt=request.no_system_prompt,
            debug=request.debug,
            profile=launch_profile,
            managed_session=managed_session,
            inject_system_prompt=inject_system_prompt,
            user_supplied_system_prompt=user_supplied_system_prompt,
        )
    except Exception:
        stack.close()
        raise
    return _CapturedRunContext(
        request=request,
        profile=launch_profile,
        prepared=prepared,
        managed_session=managed_session,
        build_invocation=build_invocation,
        resource_stack=stack,
    )


def _persist_owned_session_facts(ctx: _CapturedRunContext) -> None:
    from transport_matters.cli.launch_profile import persist_owned_session_facts

    if ctx.managed_session is None:
        return
    persist_owned_session_facts(
        ctx.profile,
        ctx.managed_session,
        run_id=ctx.prepared.run_id,
        storage_root=ctx.prepared.resolved_storage,
        home_dir=ctx.request.home_dir,
    )


def _write_workspace_manifest(
    ctx: _CapturedRunContext,
    wslock: WorkspaceLock,
    *,
    proxy_port: int,
    web_port: int,
) -> None:
    from transport_matters.cli.launch_runtime import write_workspace_manifest

    write_workspace_manifest(
        manifest_path=wslock.manifest_path,
        working_dir=ctx.prepared.working_dir,
        storage_dir=ctx.prepared.resolved_storage,
        run_id=ctx.prepared.run_id,
        home_dir=ctx.request.home_dir,
        proxy_port=proxy_port,
        web_port=web_port,
    )


def _raise_prepare_outcome(outcome: LaunchBindFailureOutcome | LaunchExitOutcome) -> None:
    from transport_matters.cli.runner import LaunchBindFailureOutcome

    if isinstance(outcome, LaunchBindFailureOutcome):
        raise outcome.failure
    message = outcome.error or f"captured run exited during prepare (code {outcome.exit_code})"
    raise RuntimeError(message)


def _claude_not_found_hint() -> str:
    from transport_matters.cli.identity import CLI_COMMAND

    return (
        "Install Claude Code, or point at an existing install:\n"
        "  npm install -g @anthropic-ai/claude-code\n"
        "  # or\n"
        f"  {CLI_COMMAND} claude --claude-bin /path/to/claude\n"
        "  # or run proxy-only:\n"
        f"  {CLI_COMMAND} claude --no-claude"
    )
