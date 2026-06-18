from __future__ import annotations

import tomllib
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from transport_matters.env_keys import ENV_PREFIX
from transport_matters.storage_roots import default_storage_root

DATABASE_URL_GUIDANCE = (
    "set TRANSPORT_MATTERS_DATABASE_URL, or add [database] url to settings.toml under "
    "$TRANSPORT_MATTERS_HOME (default ~/.transport-matters); a starter is created from "
    "settings.example.toml on first launch"
)
TEST_DATABASE_URL_GUIDANCE = (
    "set TRANSPORT_MATTERS_TEST_DATABASE_URL or TRANSPORT_MATTERS_DATABASE_URL, or add "
    "[database] test_url or [database] url to settings.toml under $TRANSPORT_MATTERS_HOME "
    "(default ~/.transport-matters; copy settings.example.toml)"
)
SETTINGS_FILENAME = "settings.toml"
SETTINGS_EXAMPLE_FILENAME = "settings.example.toml"


class SettingsFileError(ValueError):
    pass


class MissingDatabaseConfigError(RuntimeError):
    pass


class DatabaseSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = None
    test_url: str | None = None


class TomlSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)


class Settings(BaseSettings):
    """Runtime configuration.

    Transport Matters runtime fields are overridden via `TRANSPORT_MATTERS_*`
    environment variables. Database defaults come from `settings.toml`, with env
    variables as the override layer. The CLI (`transport-matters claude`) writes
    the relevant env vars before it execs `mitmdump`, so flag overrides reach the
    addon through the same mechanism as user-set env vars.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        extra="ignore",
    )

    app_name: str = "Transport Matters"
    debug: bool = False

    log_json: bool = False

    proxy_port: int = 8787
    web_port: int = 8788
    web_runtime: Literal["embedded", "external"] = "embedded"
    default_client_passthrough: tuple[str, ...] = ()
    upstream_url: str | None = None
    storage_dir: Path = Field(default_factory=default_storage_root)
    # Per-launch session boundary created by ``transport-matters claude``.
    # This is Transport Matters run identity, distinct from any provider
    # metadata session id inside captured requests. ``None`` for direct-uvicorn
    # dev runs and tests unless explicitly injected.
    run_id: str | None = None
    # Working directory captured by ``transport-matters claude`` at launch.
    # Flowed through the child env (TRANSPORT_MATTERS_CWD) so ``/api/v1/meta``
    # returns the invocation CWD rather than the addon process's live CWD.
    # Otherwise running the CLI from a subdirectory (e.g. ``api/``) leaks that
    # subdirectory into project-scoped overlays. ``None`` when the API is run
    # outside ``transport-matters claude`` (dev, tests); in that case the
    # endpoint falls back to :meth:`Path.cwd`.
    cwd: Path | None = None
    # Harness (``claude`` | ``codex`` | ...) for this launch, set by the CLI alongside
    # ``run_id``/``cwd``. Flowed so the wire binding (and thus the ``session`` row) carries the harness
    # before any transcript turn lands. ``None`` outside a managed launch (dev, tests).
    harness: str | None = None
    # Managed-mint (§5.2b/§5.2c): provider-neutral. The native id the launcher minted (== the
    # wire-observed session id) and the JSON ``source_descriptor`` for the transcript it owns. The
    # addon stamps the descriptor onto the session whose wire id matches ``owned_native_session_id``
    # (a non-owned id matches nothing and stays pending). ``None`` for unmanaged runs (dev, tests).
    owned_native_session_id: str | None = None
    owned_source_descriptor: str | None = None
    launch_fields: dict[str, Any] = Field(default_factory=dict)  # Any: JSON env carrier.
    # Managed ``--agent-home-dir`` for this launch (§11.1), set by the CLI alongside ``harness``/``run_id``.
    # The addon threads it onto the binding so ``locate`` resolves the transcript root under the managed
    # home (external-adoption-under-managed-home) and the durable ``sessions.json`` records it. ``None``
    # outside a managed launch or when no ``--agent-home-dir`` was passed (the CLI's native home).
    agent_home_dir: Path | None = None
    breakpoint_timeout_s: float = 300.0
    breakpoint_skip_models: list[str] = []
    database_url: str | None = Field(
        default=None,
        description="Env override from TRANSPORT_MATTERS_DATABASE_URL.",
    )
    test_database_url: str | None = Field(
        default=None,
        description="Test env override from TRANSPORT_MATTERS_TEST_DATABASE_URL.",
    )
    database: DatabaseSettings = Field(
        default_factory=DatabaseSettings,
        description="Database values loaded from settings.toml. Call resolve_* for precedence.",
    )
    captured_run_spawn_concurrency: int = Field(default=6, ge=1)
    session_pool_min_size: int = 0
    session_pool_max_size: int = Field(default=10, ge=2)

    # DNS rebinding defense: a rebound origin reaches the loopback server
    # same-origin, where CORS never applies, so the Host header is the only
    # signal left. Loopback names only; an operator binding beyond loopback
    # (LAN IP, *.local, reverse proxy) must extend this allowlist via
    # TRANSPORT_MATTERS_TRUSTED_HOSTS or settings.toml, or every request 400s.
    # The test suite injects its harness hosts in conftest.py, never here.
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "::1"]
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5175",
    ]
    cors_methods: list[str] = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
    cors_headers: list[str] = ["Content-Type", "Authorization"]

    @classmethod
    def load(cls) -> Settings:
        env_settings = cls()
        # Operator config (settings.toml) is read from the canonical
        # $TRANSPORT_MATTERS_HOME root, NOT the per-run STORAGE_DIR a launch injects
        # into the child env. settings_path() resolves default_storage_root() (HOME-aware).
        return cls.load_from(settings_path(), env_settings=env_settings)

    @classmethod
    def load_from(cls, path: Path, *, env_settings: Settings | None = None) -> Settings:
        base_settings = env_settings if env_settings is not None else cls()
        toml_settings = load_toml_settings(path)
        return base_settings.model_copy(update={"database": toml_settings.database})


def settings_path(storage_dir: Path | None = None) -> Path:
    return (storage_dir if storage_dir is not None else default_storage_root()) / SETTINGS_FILENAME


def settings_example_text() -> str:
    """Return the packaged ``settings.example.toml`` template text."""
    return (files("transport_matters") / SETTINGS_EXAMPLE_FILENAME).read_text(encoding="utf-8")


def ensure_settings_scaffold(storage_dir: Path | None = None) -> Path | None:
    """Create ``settings.toml`` under the config home from the packaged example if absent.

    The config home is ``$TRANSPORT_MATTERS_HOME`` (default ``~/.transport-matters``);
    pass ``storage_dir`` to override (tests). Returns the created path, or ``None`` when a
    settings file already exists.
    """
    target = settings_path(storage_dir)
    if target.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(settings_example_text(), encoding="utf-8")
    return target


def load_toml_settings(path: Path) -> TomlSettings:
    if not path.exists():
        return TomlSettings()
    try:
        with path.open("rb") as handle:
            return TomlSettings.model_validate(tomllib.load(handle))
    except tomllib.TOMLDecodeError as exc:
        raise SettingsFileError(f"malformed settings.toml at {path}: {exc}") from exc
    except ValidationError as exc:
        raise SettingsFileError(f"invalid settings.toml at {path}: {exc}") from exc


def resolve_database_url(settings: Settings) -> str:
    resolved = settings.database_url or settings.database.url
    if resolved:
        return resolved
    raise MissingDatabaseConfigError(DATABASE_URL_GUIDANCE)


def resolve_test_database_url(settings: Settings) -> str:
    resolved = (
        settings.test_database_url
        or settings.database_url
        or settings.database.test_url
        or settings.database.url
    )
    if resolved:
        return resolved
    raise MissingDatabaseConfigError(TEST_DATABASE_URL_GUIDANCE)


@lru_cache
def get_settings() -> Settings:
    return Settings.load()


__all__ = [
    "DATABASE_URL_GUIDANCE",
    "SETTINGS_EXAMPLE_FILENAME",
    "SETTINGS_FILENAME",
    "TEST_DATABASE_URL_GUIDANCE",
    "DatabaseSettings",
    "MissingDatabaseConfigError",
    "Settings",
    "SettingsFileError",
    "TomlSettings",
    "ensure_settings_scaffold",
    "get_settings",
    "load_toml_settings",
    "resolve_database_url",
    "resolve_test_database_url",
    "settings_example_text",
    "settings_path",
]
