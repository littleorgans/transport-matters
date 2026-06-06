import logging
import logging.config
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from transport_matters.api.v1.router import api_router
from transport_matters.config import MissingDatabaseConfigError, get_settings, resolve_database_url
from transport_matters.session.listen import SessionEventHub, SessionEventListener
from transport_matters.session.pool import create_async_pool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.responses import Response
    from starlette.types import Scope

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


class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if (
                exc.status_code != 404
                or _looks_like_api_path(path, scope)
                or _looks_like_asset_path(path)
            ):
                raise
            return await super().get_response("index.html", scope)


def _looks_like_api_path(path: str, scope: Scope) -> bool:
    scope_path = scope.get("path")
    if isinstance(scope_path, str):
        return scope_path == "/api" or scope_path.startswith("/api/")
    return path == "api" or path.startswith("api/")


def _looks_like_asset_path(path: str) -> bool:
    from pathlib import Path

    return "." in Path(path).name or path.startswith("assets/")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s", app.title)
    session_pool = None
    session_listener = None
    app.state.session_event_hub = SessionEventHub()
    app.state.session_pool = None
    app.state.session_event_listener = None
    try:
        database_url = resolve_database_url(get_settings())
        session_pool = create_async_pool(database_url)
        await session_pool.open()
        session_listener = SessionEventListener(database_url, app.state.session_event_hub)
        await session_listener.start()
        app.state.session_pool = session_pool
        app.state.session_event_listener = session_listener
    except MissingDatabaseConfigError as exc:
        logger.info("Session store disabled: %s", exc)
    except Exception:
        logger.exception("Session store lifecycle failed to start")
        app.state.session_pool = None
        app.state.session_event_listener = None
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

    www_dir = Path(__file__).parent / "www"
    if www_dir.exists():
        app.mount("/", SpaStaticFiles(directory=www_dir, html=True), name="www")

    return app


app = create_app()
