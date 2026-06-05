from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from transport_matters.env_keys import ENV_PREFIX
from transport_matters.storage_roots import default_storage_root


class Settings(BaseSettings):
    """Runtime configuration.

    All fields can be overridden via `TRANSPORT_MATTERS_*` environment variables
    or a local `.env` file. The CLI (`transport-matters claude`) writes the
    relevant env vars before it execs `mitmdump`, so flag overrides reach the
    addon through the same mechanism as user-set env vars.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix=ENV_PREFIX,
        extra="ignore",
    )

    app_name: str = "Transport Matters"
    debug: bool = False

    log_json: bool = False

    proxy_port: int = 8787
    web_port: int = 8788
    storage_dir: Path = default_storage_root()
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
    # Harness cli (``claude`` | ``codex`` | ...) for this launch, set by the CLI alongside
    # ``run_id``/``cwd``. Flowed so the wire binding (and thus the ``session`` row) carries the cli
    # before any transcript turn lands. ``None`` outside a managed launch (dev, tests).
    cli: str | None = None
    # Managed-mint (§5.2b): the codex native uuid the launcher minted (== the wire-observed thread
    # id) and the JSON ``source_descriptor`` for the pre-seeded rollout it owns. The addon stamps the
    # descriptor onto the codex session whose wire id matches ``codex_native_session_id`` (a non-owned
    # codex id matches nothing and stays pending). ``None`` for non-codex / unmanaged runs.
    codex_native_session_id: str | None = None
    codex_source_descriptor: str | None = None
    breakpoint_timeout_s: float = 300.0
    breakpoint_skip_models: list[str] = []

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    cors_methods: list[str] = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
    cors_headers: list[str] = ["Content-Type", "Authorization"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
