import logging
import logging.config
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from transport_matters.api.v1.router import api_router
from transport_matters.config import MissingDatabaseConfigError, get_settings, resolve_database_url
from transport_matters.session.listen import SessionEventHub, SessionEventListener
from transport_matters.session.pool import create_async_pool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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
    session_pool = None
    session_listener = None
    app.state.session_event_hub = SessionEventHub()
    try:
        database_url = resolve_database_url(get_settings())
        session_pool = create_async_pool(database_url)
        await session_pool.open()
        app.state.session_pool = session_pool
        session_listener = SessionEventListener(database_url, app.state.session_event_hub)
        app.state.session_event_listener = session_listener
        await session_listener.start()
    except MissingDatabaseConfigError as exc:
        logger.info("Session store disabled: %s", exc)
    except Exception:
        logger.exception("Session store lifecycle failed to start")
        if session_listener is not None:
            await session_listener.aclose()
        if session_pool is not None:
            await session_pool.close()
    try:
        yield
    finally:
        if session_listener is not None:
            await session_listener.aclose()
        if session_pool is not None:
            await session_pool.close()
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
            "()": "transport_matters.logging.JSONFormatter",
        }
    logging.config.dictConfig(config)

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=settings.cors_methods,
        allow_headers=settings.cors_headers,
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
