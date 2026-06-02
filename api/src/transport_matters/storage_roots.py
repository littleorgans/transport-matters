"""Backend owned storage root paths."""

from pathlib import Path

DEFAULT_STORAGE_DIRNAME = ".transport-matters"
WORKSPACES_DIRNAME = "workspaces"


def default_storage_root() -> Path:
    """Return the default backend storage root under the user's home."""
    return Path.home() / DEFAULT_STORAGE_DIRNAME


def default_workspaces_root() -> Path:
    """Return the default shared workspace manifest root."""
    return default_storage_root() / WORKSPACES_DIRNAME
