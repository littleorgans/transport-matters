import subprocess
import sys
from pathlib import Path

import pytest

from transport_matters import env_keys
from transport_matters.channel import (
    activate_channel,
    all_channel_specs,
    resolve_channel_id,
    resolve_channel_spec,
)
from transport_matters.config import (
    DatabaseSettings,
    MissingDatabaseConfigError,
    Settings,
    get_settings,
    resolve_database_url,
)
from transport_matters.storage.disk_layout import DiskStorageLayout


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()


def test_all_channel_specs_loads_packaged_json() -> None:
    specs = all_channel_specs()

    assert tuple(spec.id for spec in specs) == ("stable", "preview")
    stable, preview = specs
    assert stable.label == "Stable"
    assert stable.home == Path.home() / ".transport-matters"
    assert stable.database_name == "transport_matters"
    assert stable.proxy_port == 8787
    assert stable.web_port == 8788
    assert stable.electron_app_name == "Transport Matters"
    assert stable.electron_app_id == "io.helioy.transport-matters"
    assert stable.electron_user_data is None
    assert stable.dock_icon == "default"
    assert stable.badge is None
    assert preview.label == "Preview"
    assert preview.home == Path.home() / ".transport-matters-preview"
    assert preview.database_name == "transport_matters_preview"
    assert preview.proxy_port == 8797
    assert preview.web_port == 8798
    assert preview.electron_app_name == "Transport Matters Preview"
    assert preview.electron_app_id == "io.helioy.transport-matters.preview"
    assert preview.electron_user_data == preview.home / "electron-user-data"
    assert preview.dock_icon == "preview-amber"
    assert preview.badge is not None
    assert preview.badge.text == "PREVIEW"
    assert preview.badge.color == "amber"
    assert preview.badge.hex == "#f59e0b"


def test_channel_module_imports_in_subprocess() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import transport_matters.channel"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_resolve_channel_id_defaults_to_stable() -> None:
    assert resolve_channel_id(None, {}) == "stable"


def test_resolve_channel_id_uses_env_and_explicit_value_wins() -> None:
    env = {env_keys.CHANNEL: "preview"}

    assert resolve_channel_id(None, env) == "preview"
    assert resolve_channel_id("stable", env) == "stable"


def test_resolve_channel_id_rejects_bad_format() -> None:
    with pytest.raises(ValueError, match="invalid channel id"):
        resolve_channel_id("Preview", {})


def test_resolve_channel_id_rejects_unknown_id() -> None:
    with pytest.raises(ValueError, match="unknown channel"):
        resolve_channel_id("canary", {})


def test_resolve_channel_spec_returns_preview() -> None:
    spec = resolve_channel_spec("preview", {})

    assert spec.id == "preview"
    assert spec.home == Path.home() / ".transport-matters-preview"


def test_activate_channel_sets_env_and_clears_settings_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(env_keys.CHANNEL, raising=False)
    assert get_settings().channel == "stable"

    spec = activate_channel("preview")

    assert spec.id == "preview"
    assert get_settings().channel == "preview"


def test_resolve_database_url_substitutes_only_database_name() -> None:
    settings = Settings(
        channel="preview",
        database_url="postgresql://tm:tm@localhost:55432/original?sslmode=disable",
    )

    assert (
        resolve_database_url(settings)
        == "postgresql://tm:tm@localhost:55432/transport_matters_preview?sslmode=disable"
    )


def test_resolve_database_url_still_requires_configured_server() -> None:
    settings = Settings(
        channel="preview",
        database_url=None,
        database=DatabaseSettings(url=None),
    )

    with pytest.raises(MissingDatabaseConfigError):
        resolve_database_url(settings)


def test_disk_storage_layout_default_root_is_lazy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(env_keys.HOME, raising=False)
    monkeypatch.setenv(env_keys.CHANNEL, "stable")
    assert DiskStorageLayout().root == Path.home() / ".transport-matters"

    monkeypatch.setenv(env_keys.CHANNEL, "preview")
    assert DiskStorageLayout().root == Path.home() / ".transport-matters-preview"
