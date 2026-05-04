from pathlib import Path

import pytest

from transport_matters.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()


def test_settings_use_transport_matters_env_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = tmp_path / "transport-storage"
    monkeypatch.setenv("TRANSPORT_MATTERS_STORAGE_DIR", str(storage))
    monkeypatch.setenv("TRANSPORT_MATTERS_WEB_PORT", "9901")
    monkeypatch.setenv("TRANSPORT_MATTERS_PROXY_PORT", "9900")
    monkeypatch.setenv("TRANSPORT_MATTERS_RUN_ID", "run-new")
    monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(tmp_path))
    monkeypatch.setenv("TRANSPORT_MATTERS_DEBUG", "true")

    settings = get_settings()

    assert settings.storage_dir == storage
    assert settings.web_port == 9901
    assert settings.proxy_port == 9900
    assert settings.run_id == "run-new"
    assert settings.cwd == tmp_path
    assert settings.debug is True


def test_settings_default_storage_root_uses_transport_matters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)

    settings = get_settings()

    assert settings.storage_dir == Path.home() / ".transport-matters"


def test_settings_default_app_name_uses_transport_matters() -> None:
    settings = get_settings()

    assert settings.app_name == "Transport Matters"


def test_settings_ignore_old_manicure_env_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_prefix = "MANI" + "CURE_"
    monkeypatch.setenv(f"{old_prefix}STORAGE_DIR", str(tmp_path / "old-storage"))
    monkeypatch.setenv(f"{old_prefix}WEB_PORT", "9901")
    monkeypatch.setenv(f"{old_prefix}PROXY_PORT", "9900")
    monkeypatch.setenv(f"{old_prefix}RUN_ID", "run-old")
    monkeypatch.setenv(f"{old_prefix}CWD", str(tmp_path))
    monkeypatch.setenv(f"{old_prefix}DEBUG", "true")

    settings = get_settings()

    assert settings.storage_dir != tmp_path / "old-storage"
    assert settings.web_port == 8788
    assert settings.proxy_port == 8787
    assert settings.run_id is None
    assert settings.cwd is None
    assert settings.debug is False
