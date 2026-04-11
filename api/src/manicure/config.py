from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    All fields can be overridden via `MANICURE_*` environment variables or
    a local `.env` file. The CLI (`manicure start`) writes the relevant
    env vars before it execs `mitmdump`, so flag overrides reach the
    addon through the same mechanism as user-set env vars.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MANICURE_",
        extra="ignore",
    )

    app_name: str = "manicure"
    debug: bool = False

    log_json: bool = False

    proxy_port: int = 8787
    web_port: int = 8788
    storage_dir: Path = Path.home() / ".manicure"


@lru_cache
def get_settings() -> Settings:
    return Settings()
