from pathlib import Path

import pytest
from psycopg import Connection

from transport_matters import env_keys, session
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
    monkeypatch.setenv("TRANSPORT_MATTERS_CHANNEL", "preview")
    monkeypatch.setenv("TRANSPORT_MATTERS_DEBUG", "true")

    settings = get_settings()

    assert settings.storage_dir == storage
    assert settings.web_port == 9901
    assert settings.proxy_port == 9900
    assert settings.run_id == "run-new"
    assert settings.cwd == tmp_path
    assert settings.channel == "preview"
    assert settings.debug is True


def test_settings_read_managed_home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The managed --agent-home-dir reaches the addon via the OWNED_* env channel (§11.1) so adapter binding
    # stamps it onto the binding and locate resolves the transcript root under the managed home.
    home = tmp_path / "managed-home"
    monkeypatch.setenv("TRANSPORT_MATTERS_AGENT_HOME_DIR", str(home))
    assert get_settings().agent_home_dir == home


def test_settings_read_default_client_passthrough_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        env_keys.DEFAULT_CLIENT_PASSTHROUGH,
        '["--dangerously-skip-permissions","--model","sonnet"]',
    )

    assert get_settings().default_client_passthrough == (
        "--dangerously-skip-permissions",
        "--model",
        "sonnet",
    )


def test_settings_home_dir_defaults_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRANSPORT_MATTERS_AGENT_HOME_DIR", raising=False)
    assert get_settings().agent_home_dir is None


def test_shipped_trusted_hosts_default_is_loopback_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The conftest injects harness hosts ("testserver", "test") via env; the
    # SHIPPED default is a security posture and must stay loopback-only.
    monkeypatch.delenv("TRANSPORT_MATTERS_TRUSTED_HOSTS", raising=False)
    assert get_settings().trusted_hosts == ["localhost", "127.0.0.1", "::1"]


def test_settings_default_storage_root_uses_transport_matters(
    clear_channel_storage_env: None,
) -> None:
    settings = get_settings()

    assert settings.storage_dir == Path.home() / ".transport-matters"


def test_settings_preview_channel_relocates_default_storage_root(
    monkeypatch: pytest.MonkeyPatch, clear_channel_storage_env: None
) -> None:
    monkeypatch.setenv("TRANSPORT_MATTERS_CHANNEL", "preview")

    settings = get_settings()

    assert settings.channel == "preview"
    assert settings.storage_dir == Path.home() / ".transport-matters-preview"


def test_transport_matters_home_relocates_storage_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from transport_matters.storage_roots import default_storage_root

    monkeypatch.setenv("TRANSPORT_MATTERS_HOME", str(tmp_path / "custom-home"))

    assert default_storage_root() == tmp_path / "custom-home"


def test_settings_toml_read_from_home_not_per_run_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Operator config lives at $TRANSPORT_MATTERS_HOME/settings.toml and must be read
    # regardless of the per-run STORAGE_DIR a launch sets into the child env (bug #3).
    home = tmp_path / "home"
    home.mkdir()
    (home / "settings.toml").write_text(
        '[database]\nurl = "postgresql://home/db"\n', encoding="utf-8"
    )
    per_run = tmp_path / "run-storage"
    per_run.mkdir()
    monkeypatch.setenv("TRANSPORT_MATTERS_HOME", str(home))
    monkeypatch.setenv("TRANSPORT_MATTERS_STORAGE_DIR", str(per_run))
    monkeypatch.delenv("TRANSPORT_MATTERS_DATABASE_URL", raising=False)
    get_settings.cache_clear()

    assert get_settings().database.url == "postgresql://home/db"


def test_home_isolation_ignores_malformed_default_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression (conftest collection isolation): a malformed settings.toml at the OS-home
    # default must NOT break loading when $TRANSPORT_MATTERS_HOME points at a clean root.
    poisoned_os_home = tmp_path / "oshome"
    (poisoned_os_home / ".transport-matters").mkdir(parents=True)
    (poisoned_os_home / ".transport-matters" / "settings.toml").write_text(
        "[database\n", encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(poisoned_os_home))
    clean_home = tmp_path / "clean"
    clean_home.mkdir()
    monkeypatch.setenv("TRANSPORT_MATTERS_HOME", str(clean_home))
    get_settings.cache_clear()

    # Reads the clean HOME, not the poisoned OS-home default -> no SettingsFileError.
    assert get_settings().database.url is None


def test_ensure_settings_scaffold_creates_from_packaged_example(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from transport_matters.config import ensure_settings_scaffold, settings_example_text

    monkeypatch.setenv("TRANSPORT_MATTERS_HOME", str(tmp_path))

    created = ensure_settings_scaffold()

    assert created == tmp_path / "settings.toml"
    assert (tmp_path / "settings.toml").read_text(encoding="utf-8") == settings_example_text()
    assert "[database]" in settings_example_text()


def test_ensure_settings_scaffold_noop_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from transport_matters.config import ensure_settings_scaffold

    monkeypatch.setenv("TRANSPORT_MATTERS_HOME", str(tmp_path))
    (tmp_path / "settings.toml").write_text('[database]\nurl = "x"\n', encoding="utf-8")

    assert ensure_settings_scaffold() is None
    assert (tmp_path / "settings.toml").read_text(encoding="utf-8") == '[database]\nurl = "x"\n'


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

    assert resolve_database_url(settings) == "postgresql://env/transport_matters"
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
