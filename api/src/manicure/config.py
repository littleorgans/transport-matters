from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "manicure"
    debug: bool = False

    log_json: bool = False

    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 30

    @model_validator(mode="after")
    def validate_secret_key(self) -> "Settings":
        if not self.debug and self.secret_key == "change-me-in-production":
            raise ValueError(
                "SECRET_KEY must be set in production. "
                "Set SECRET_KEY env var or DEBUG=true for development."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
