"""Domain types and constants for captured-run preparation.

The pure vocabulary shared across the captured-run modules: the launch
request, the spawn spec and lease returned by
:func:`prepare_captured_run`, the bind-conflict exception, and the
web-runtime literals. No launch logic lives here, so the dependency
factory (:mod:`captured_run_dependencies`) and the orchestration
(:mod:`captured_run`) can both depend on it without an import cycle.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping
    from contextlib import ExitStack
    from pathlib import Path

    from transport_matters.cli.launch_profile import ManagedSession
    from transport_matters.cli.runner import ManagedClient
    from transport_matters.cli.runtime_home import RuntimeTemplateRef
    from transport_matters.lock import WorkspaceLock

__all__ = [
    "CLAUDE_CLIENT_NAME",
    "CLAUDE_UPSTREAM_DEFAULT",
    "CODEX_CLIENT_NAME",
    "WEB_RUNTIME_EMBEDDED",
    "WEB_RUNTIME_EXTERNAL",
    "CapturedRunBindConflict",
    "CapturedRunCli",
    "CapturedRunLease",
    "CapturedRunRequest",
    "CapturedRunSpawnSpec",
    "CapturedRunWebRuntime",
]

CLAUDE_CLIENT_NAME = "claude"
CODEX_CLIENT_NAME = "codex"
CLAUDE_UPSTREAM_DEFAULT = "https://api.anthropic.com"
CapturedRunCli = Literal["claude", "codex"]
CapturedRunWebRuntime = Literal["embedded", "external"]
WEB_RUNTIME_EMBEDDED: CapturedRunWebRuntime = "embedded"
WEB_RUNTIME_EXTERNAL: CapturedRunWebRuntime = "external"


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
    web_runtime: CapturedRunWebRuntime = WEB_RUNTIME_EMBEDDED
    default_client_passthrough: tuple[str, ...] = ()
    runtime_template: RuntimeTemplateRef | None = None
    launch_fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CapturedRunSpawnSpec:
    run_id: str
    working_dir: Path
    storage_dir: Path
    proxy_port: int
    web_port: int | None
    mitmdump_log: Path
    client: ManagedClient | None
    launch_env: dict[str, str]
    managed_session: ManagedSession | None
    client_name: str = CLAUDE_CLIENT_NAME


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


class CapturedRunBindConflict(RuntimeError):
    """Raised when captured-run proxy bind retries exhaust without a free pair."""
