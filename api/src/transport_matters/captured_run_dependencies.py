"""Concrete Claude launch dependencies behind the neutral captured-run seam.

:class:`CapturedRunDependencies` is the dependency-injection contract the
captured-run orchestration consumes; :func:`default_claude_run_dependencies`
wires it to the real CLI helpers (addon discovery, mitmdump resolution,
port allocation, prompt injection, session-store probing). Tests pass
their own callables to keep the orchestration hermetic.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from functools import partial
from importlib.resources import files
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from importlib.resources.abc import Traversable

__all__ = [
    "CapturedRunDependencies",
    "default_claude_run_dependencies",
]


@dataclass(frozen=True, slots=True)
class CapturedRunDependencies:
    require_addon: Callable[[], Traversable]
    resolve_mitmdump: Callable[[], str | None]
    which: Callable[..., str | None]
    port_in_use: Callable[[int], bool]
    allocate_port_pair: Callable[[], tuple[int, int]]
    inject_system_prompt: Callable[..., list[str]]
    user_supplied_system_prompt: Callable[[list[str]], bool]
    check_session_store: Callable[[], str | None]


def default_claude_run_dependencies(
    *,
    require_addon: Callable[[], Traversable] | None = None,
    which: Callable[..., str | None] | None = None,
    get_scripts_dir: Callable[[str], str | None] | None = None,
    port_in_use: Callable[[int], bool] | None = None,
    allocate_port_pair: Callable[[], tuple[int, int]] | None = None,
    inject_system_prompt: Callable[..., list[str]] | None = None,
    user_supplied_system_prompt: Callable[[list[str]], bool] | None = None,
    check_session_store: Callable[[], str | None] | None = None,
) -> CapturedRunDependencies:
    """Return the concrete Claude launch dependencies behind the neutral seam."""
    import sysconfig

    import typer

    from transport_matters.cli.identity import CLI_COMMAND
    from transport_matters.cli.launch_runtime import (
        check_session_store as default_check_session_store,
    )
    from transport_matters.cli.launch_runtime import (
        resolve_mitmdump_executable,
    )
    from transport_matters.cli.net import port_in_use as default_port_in_use
    from transport_matters.cli.ports import allocate_port_pair as default_allocate_port_pair
    from transport_matters.cli.prompt import (
        inject_system_prompt as default_inject_system_prompt,
    )
    from transport_matters.cli.prompt import (
        user_supplied_system_prompt as default_user_supplied_system_prompt,
    )

    def require_packaged_addon() -> Traversable:
        addon_traversable = files("transport_matters") / "addon.py"
        if not addon_traversable.is_file():
            typer.secho(
                "error: could not locate the Transport Matters mitmproxy addon.",
                fg=typer.colors.RED,
                err=True,
            )
            typer.echo(
                "The package may be corrupted. Try reinstalling:\n"
                f"  uv tool install --force {CLI_COMMAND}",
                err=True,
            )
            raise typer.Exit(2)
        return addon_traversable

    resolved_which = shutil.which if which is None else which
    resolved_get_scripts_dir = sysconfig.get_path if get_scripts_dir is None else get_scripts_dir
    return CapturedRunDependencies(
        require_addon=require_packaged_addon if require_addon is None else require_addon,
        resolve_mitmdump=partial(
            resolve_mitmdump_executable,
            which=resolved_which,
            get_scripts_dir=resolved_get_scripts_dir,
        ),
        which=resolved_which,
        port_in_use=default_port_in_use if port_in_use is None else port_in_use,
        allocate_port_pair=(
            default_allocate_port_pair if allocate_port_pair is None else allocate_port_pair
        ),
        inject_system_prompt=(
            default_inject_system_prompt if inject_system_prompt is None else inject_system_prompt
        ),
        user_supplied_system_prompt=(
            default_user_supplied_system_prompt
            if user_supplied_system_prompt is None
            else user_supplied_system_prompt
        ),
        check_session_store=(
            default_check_session_store if check_session_store is None else check_session_store
        ),
    )
