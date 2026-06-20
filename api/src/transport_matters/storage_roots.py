"""Backend owned storage root paths."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from transport_matters import env_keys
from transport_matters.channel import resolve_channel_spec

if TYPE_CHECKING:
    from collections.abc import Mapping

WORKSPACES_DIRNAME = "workspaces"


def default_storage_root(
    channel: str | None = None, *, env: Mapping[str, str] | None = None
) -> Path:
    """Return the backend storage/config root.

    Honours ``$TRANSPORT_MATTERS_HOME`` so operators can relocate the whole
    ``~/.transport-matters`` tree (operator config plus per-run data). This is the
    canonical home for ``settings.toml`` and is read independent of any per-run
    ``STORAGE_DIR`` a launch injects into the child env. Defaults to the active
    channel home.
    """
    source_env = os.environ if env is None else env
    override = source_env.get(env_keys.HOME)
    if override:
        return Path(override).expanduser()
    return resolve_channel_spec(channel, source_env).home


def default_workspaces_root() -> Path:
    """Return the default shared workspace manifest root."""
    return default_storage_root() / WORKSPACES_DIRNAME
