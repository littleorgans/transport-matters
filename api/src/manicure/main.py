import logging
import logging.config
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from manicure.api.v1.router import api_router
from manicure.config import get_settings

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(message)s"

# Shared log config. Used by __main__.py (passed to uvicorn.run so the
# reloader parent gets it) and by create_app (for direct uvicorn invocations).
LOG_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": LOG_FORMAT},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": [], "propagate": True},
        "uvicorn.error": {"handlers": [], "propagate": True},
        "uvicorn.access": {"handlers": [], "propagate": True},
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
}

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s", app.title)
    yield
    logger.info("Shutting down %s", app.title)


def create_app() -> FastAPI:
    settings = get_settings()

    import copy

    config = copy.deepcopy(LOG_CONFIG)
    config["root"] = {
        "level": "DEBUG" if settings.debug else "INFO",
        "handlers": ["console"],
    }
    if settings.log_json:
        config["formatters"]["default"] = {
            "()": "manicure.logging.JSONFormatter",
        }
    logging.config.dictConfig(config)

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router, prefix="/api")

    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    www_dir = Path(__file__).parent / "www"
    if www_dir.exists():
        app.mount("/", StaticFiles(directory=www_dir, html=True), name="www")

    return app


app = create_app()
