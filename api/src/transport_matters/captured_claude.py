"""Captured Claude launch helpers shared by pane and CLI seams."""

from __future__ import annotations

from typing import TYPE_CHECKING

from transport_matters.captured_run_models import WEB_RUNTIME_EMBEDDED, CapturedRunWebRuntime

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from transport_matters.cli.launch_profile import LaunchProfile, ManagedSession
    from transport_matters.cli.runner import ManagedClient


def build_claude_captured_invocation(
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
    web_runtime: CapturedRunWebRuntime = WEB_RUNTIME_EMBEDDED,
    default_client_passthrough: Sequence[str] = (),
    runtime_home_dir: Path | None = None,
    launch_fields: Mapping[str, object] | None = None,
    bypass_permissions: bool = False,
) -> Callable[[int, int | None], tuple[list[str], dict[str, str], ManagedClient | None]]:
    """Build the retry-safe invocation factory for a captured Claude launch."""
    from transport_matters.cli.home_seed import apply_claude_proxy_env_settings
    from transport_matters.cli.launch_runtime import (
        build_mitmdump_argv,
    )
    from transport_matters.cli.net import loopback_http_url
    from transport_matters.cli.runner import ManagedClient
    from transport_matters.launch_environment import (
        HARNESS_NAME_CLAUDE,
        build_launch_env,
        build_managed_child_env,
    )

    def build_invocation(
        proxy_port: int,
        web_port: int | None,
    ) -> tuple[list[str], dict[str, str], ManagedClient | None]:
        if web_runtime == WEB_RUNTIME_EMBEDDED and web_port is None:
            raise ValueError("embedded web runtime requires a web port")
        passthrough = list(claude_passthrough_user)
        should_inject_prompt = (
            not no_claude
            and not no_system_prompt
            and web_port is not None
            and not user_supplied_system_prompt(passthrough)
        )
        if should_inject_prompt:
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
            web_runtime=web_runtime,
            harness=HARNESS_NAME_CLAUDE,
            home_dir=home_dir,
            owned_native_session_id=native_session_id,
            owned_source_descriptor=(
                managed_session.source_descriptor if managed_session is not None else None
            ),
            launch_fields=launch_fields,
            default_client_passthrough=default_client_passthrough,
        )
        argv = build_mitmdump_argv(
            mitmdump=mitmdump,
            mode=f"reverse:{upstream}",
            proxy_port=proxy_port,
            addon_path=addon_path,
            debug=debug,
        )

        proxy_url = loopback_http_url(proxy_port)
        client = None
        if claude_path is not None:
            child_home_dir = runtime_home_dir or home_dir
            if runtime_home_dir is not None:
                apply_claude_proxy_env_settings(
                    runtime_home_dir=runtime_home_dir,
                    proxy_url=proxy_url,
                    run_id=run_id,
                )
            client_env = build_managed_child_env(
                env,
                harness=HARNESS_NAME_CLAUDE,
                home_dir=child_home_dir,
                extra_env={"ANTHROPIC_BASE_URL": proxy_url},
            )
            client = ManagedClient(
                name=HARNESS_NAME_CLAUDE,
                display_name="Claude",
                argv=profile.client_argv(
                    client_path=claude_path,
                    passthrough=passthrough,
                    native_session_id=native_session_id,
                    bypass_permissions=bypass_permissions,
                ),
                env=client_env,
                cwd=working_dir,
            )
        return argv, env, client

    return build_invocation
