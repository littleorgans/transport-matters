"""Reusable captured-run preparation for managed agent launches."""

import contextlib
import os
import shutil
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import as_file
from typing import TYPE_CHECKING

from transport_matters.cli.identity import CLI_COMMAND
from transport_matters.cli.launch_profile import (
    ClaudeLaunchProfile,
    ManagedSession,
    persist_owned_session_facts,
    prepare_managed_session,
)
from transport_matters.cli.launch_runtime import (
    CLIENT_NAME_CLAUDE,
    build_launch_env,
    build_managed_child_env,
    build_mitmdump_argv,
    prepare_launch,
    write_workspace_manifest,
)
from transport_matters.cli.net import loopback_http_url
from transport_matters.cli.runner import (
    LaunchBindFailureOutcome,
    LaunchExitOutcome,
    ManagedClient,
    mitmdump_log_path,
    start_prepared_proxy,
)
from transport_matters.lock import WorkspaceLock
from transport_matters.supervisor import ProcessSupervisor
from transport_matters.workspace import run_root

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from importlib.resources.abc import Traversable
    from pathlib import Path

    from transport_matters.cli.launch_profile import LaunchProfile


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
    _supervisor: ProcessSupervisor
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
    supervisor_factory: Callable[[], ProcessSupervisor] = ProcessSupervisor,
) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
    """Prepare one captured run and return the client spawn spec plus lease."""
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
        write=True,
    )

    stack = ExitStack()
    wslock: WorkspaceLock | None = None
    supervisor: ProcessSupervisor | None = None
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
        wslock = WorkspaceLock(run_root(prepared.working_dir, prepared.run_id)).__enter__()
        write_workspace_manifest(
            manifest_path=wslock.manifest_path,
            working_dir=prepared.working_dir,
            storage_dir=prepared.resolved_storage,
            run_id=prepared.run_id,
            home_dir=request.home_dir,
            proxy_port=prepared.proxy_port,
            web_port=prepared.web_port,
        )
        if managed_session is not None:
            persist_owned_session_facts(
                launch_profile,
                managed_session,
                run_id=prepared.run_id,
                storage_root=prepared.resolved_storage,
                home_dir=request.home_dir,
            )

        mitmdump_argv, launch_env, client = build_invocation(
            prepared.proxy_port,
            prepared.web_port,
        )
        mitmdump_log = mitmdump_log_path(prepared.resolved_storage)
        supervisor = supervisor_factory()
        spawn_spec = CapturedRunSpawnSpec(
            run_id=prepared.run_id,
            working_dir=prepared.working_dir,
            storage_dir=prepared.resolved_storage,
            proxy_port=prepared.proxy_port,
            web_port=prepared.web_port,
            mitmdump_log=mitmdump_log,
            client=client,
            launch_env=launch_env,
            managed_session=managed_session,
        )
        lease = CapturedRunLease(
            spawn_spec=spawn_spec,
            _supervisor=supervisor,
            _workspace_lock=wslock,
            _resource_stack=stack,
        )
        outcome = start_prepared_proxy(
            sup=supervisor,
            mitmdump_argv=mitmdump_argv,
            mitmdump_env=launch_env,
            mitmdump_log=mitmdump_log,
            proxy_port=prepared.proxy_port,
            web_port=prepared.web_port,
        )
        if outcome is not None:
            lease.close()
            _raise_prepare_outcome(outcome)
        return spawn_spec, lease
    except Exception:
        if supervisor is not None:
            supervisor.terminate_all()
            supervisor.restore_signal_handlers()
        if wslock is not None:
            with contextlib.suppress(FileNotFoundError):
                wslock.manifest_path.unlink()
            wslock.__exit__(None, None, None)
        stack.close()
        raise


def _raise_prepare_outcome(outcome: LaunchBindFailureOutcome | LaunchExitOutcome) -> None:
    if isinstance(outcome, LaunchBindFailureOutcome):
        raise outcome.failure
    message = outcome.error or f"captured run exited during prepare (code {outcome.exit_code})"
    raise RuntimeError(message)


def _claude_not_found_hint() -> str:
    return (
        "Install Claude Code, or point at an existing install:\n"
        "  npm install -g @anthropic-ai/claude-code\n"
        "  # or\n"
        f"  {CLI_COMMAND} claude --claude-bin /path/to/claude\n"
        "  # or run proxy-only:\n"
        f"  {CLI_COMMAND} claude --no-claude"
    )
