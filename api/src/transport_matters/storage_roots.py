"""Backend owned storage root paths."""

import os
from pathlib import Path

from transport_matters import env_keys
from transport_matters.channel import resolve_channel_spec

DEFAULT_STORAGE_DIRNAME = ".transport-matters"
WORKSPACES_DIRNAME = "workspaces"


def default_storage_root() -> Path:
    """Return the backend storage/config root.

    Honours ``$TRANSPORT_MATTERS_HOME`` so operators can relocate the whole
    ``~/.transport-matters`` tree (operator config plus per-run data). This is the
    canonical home for ``settings.toml`` and is read independent of any per-run
    ``STORAGE_DIR`` a launch injects into the child env. Defaults to the active
    channel home.
    """
    override = os.environ.get(env_keys.HOME)
    if override:
        return Path(override).expanduser()
    return resolve_channel_spec().home


def default_workspaces_root() -> Path:
    """Return the default shared workspace manifest root."""
    return default_storage_root() / WORKSPACES_DIRNAME
