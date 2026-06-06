from pathlib import Path

import pytest
from psycopg import Connection

from transport_matters import session
from transport_matters.config import (
    MissingDatabaseConfigError,
    Settings,
    SettingsFileError,
    get_settings,
    resolve_database_url,
    resolve_test_database_url,
)


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


def test_settings_read_managed_home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The managed --home-dir reaches the addon via the OWNED_* env channel (§11.1) so adapter binding
    # stamps it onto the binding and locate resolves the transcript root under the managed home.
    home = tmp_path / "managed-home"
    monkeypatch.setenv("TRANSPORT_MATTERS_HOME_DIR", str(home))
    assert get_settings().home_dir == home


def test_settings_home_dir_defaults_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRANSPORT_MATTERS_HOME_DIR", raising=False)
    assert get_settings().home_dir is None


def test_settings_default_storage_root_uses_transport_matters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)

    settings = get_settings()

    assert settings.storage_dir == Path.home() / ".transport-matters"


def test_settings_default_app_name_uses_transport_matters() -> None:
    settings = get_settings()

    assert settings.app_name == "Transport Matters"


def test_settings_load_from_missing_file_yields_database_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRANSPORT_MATTERS_DATABASE_URL", raising=False)
    monkeypatch.delenv("TRANSPORT_MATTERS_TEST_DATABASE_URL", raising=False)

    settings = Settings.load_from(tmp_path / "missing-settings.toml")

    assert settings.database.url is None
    assert settings.database.test_url is None


def test_malformed_settings_toml_errors(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("[database\n", encoding="utf-8")

    with pytest.raises(SettingsFileError, match=r"malformed settings\.toml"):
        Settings.load_from(path)


def test_invalid_settings_toml_extra_keys_error(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text('[database]\nbogus = "postgresql://typo/db"\n', encoding="utf-8")

    with pytest.raises(SettingsFileError, match=r"invalid settings\.toml"):
        Settings.load_from(path)


def test_database_url_resolves_env_over_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.toml"
    path.write_text(
        '[database]\nurl = "postgresql://toml/db"\ntest_url = "postgresql://toml/test"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TRANSPORT_MATTERS_DATABASE_URL", "postgresql://env/db")
    monkeypatch.setenv("TRANSPORT_MATTERS_TEST_DATABASE_URL", "postgresql://env/test")

    settings = Settings.load_from(path)

    assert resolve_database_url(settings) == "postgresql://env/db"
    assert resolve_test_database_url(settings) == "postgresql://env/test"


def test_test_database_url_falls_back_through_env_and_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.toml"
    path.write_text(
        '[database]\nurl = "postgresql://toml/db"\ntest_url = "postgresql://toml/test"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("TRANSPORT_MATTERS_TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("TRANSPORT_MATTERS_DATABASE_URL", "postgresql://env/db")

    assert resolve_test_database_url(Settings.load_from(path)) == "postgresql://env/db"

    monkeypatch.delenv("TRANSPORT_MATTERS_DATABASE_URL", raising=False)

    assert resolve_test_database_url(Settings.load_from(path)) == "postgresql://toml/test"


def test_missing_database_url_errors_with_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRANSPORT_MATTERS_DATABASE_URL", raising=False)
    monkeypatch.delenv("TRANSPORT_MATTERS_TEST_DATABASE_URL", raising=False)

    with pytest.raises(MissingDatabaseConfigError, match="set TRANSPORT_MATTERS_DATABASE_URL"):
        resolve_database_url(Settings.load_from(tmp_path / "missing-settings.toml"))


def test_session_connect_error_does_not_attempt_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRANSPORT_MATTERS_DATABASE_URL", raising=False)
    monkeypatch.delenv("TRANSPORT_MATTERS_TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("TRANSPORT_MATTERS_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    called = False

    def fail_connect(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("connection attempted")

    monkeypatch.setattr(Connection, "connect", fail_connect)

    with pytest.raises(MissingDatabaseConfigError, match=r"settings\.example\.toml"):
        session.connect()

    assert called is False


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
