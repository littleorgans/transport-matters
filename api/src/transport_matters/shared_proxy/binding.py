"""Per-run identity threaded through shared proxy capture paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from transport_matters.storage.base import StorageBackend


@dataclass(slots=True)
class RecentAuthHolder:
    """Per-run holder for the filtered auth headers used by lazy token counts."""

    _auth: dict[str, str] | None = None

    def set(self, auth: dict[str, str] | None) -> None:
        self._auth = dict(auth) if auth else None

    def get(self) -> dict[str, str] | None:
        return dict(self._auth) if self._auth else None


@dataclass(frozen=True, slots=True)
class ProxyRunBinding:
    """Run-scoped proxy identity for addon capture and persistence."""

    run_id: str | None
    cli: str | None
    working_dir: Path | None
    storage_dir: Path
    storage: StorageBackend
    listen_port: int | None
    upstream: str | None
    agent_home_dir: Path | None
    owned_native_session_id: str | None
    owned_source_descriptor: str | None
    launch_fields: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    default_client_passthrough: tuple[str, ...] = ()
    breakpoint_skip_models: tuple[str, ...] = ()
    recent_auth: RecentAuthHolder = field(
        default_factory=RecentAuthHolder,
        compare=False,
        repr=False,
    )


async def resolve_run_storage(
    binding: ProxyRunBinding | None,
) -> tuple[StorageBackend, str | None]:
    """Resolve storage and run id from a binding, falling back to Context A globals."""

    if binding is not None:
        return binding.storage, binding.run_id

    from transport_matters.config import get_settings
    from transport_matters.storage import get_storage

    return await get_storage(), get_settings().run_id
