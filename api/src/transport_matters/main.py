import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from transport_matters.api.v1 import exchanges, meta, run_routes, session_routes, stream
from transport_matters.api.v1.router import api_router
from transport_matters.config import MissingDatabaseConfigError, get_settings, resolve_database_url
from transport_matters.session.listen import SessionEventHub, SessionEventListener
from transport_matters.session.migrate import MigrationError, apply_migrations
from transport_matters.session.pool import create_async_pool
from transport_matters.shared_proxy.manager import SharedProxyManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from psycopg import AsyncConnection
    from psycopg.rows import DictRow
    from psycopg_pool import AsyncConnectionPool
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


async def _start_session_store(
    app: FastAPI, database_url: str
) -> AsyncConnectionPool[AsyncConnection[DictRow]] | None:
    """Open the pool, auto-migrate to head, and start the event listener.

    Returns the live pool on success (with ``app.state`` wired), or ``None`` when the
    store is configured but unusable for a *recoverable* reason (connection or listener
    failure) so routes degrade to 503. Only a CONFIRMED schema-migration failure on a
    reachable database is non-recoverable and fails backend startup: a configured store
    that is merely unreachable must degrade (not crash), matching the launch-path
    preflight which already hard-blocks unreachable stores before the backend starts.
    """
    pool = create_async_pool(database_url)
    try:
        await pool.open()
    except Exception:
        logger.exception("Session store connection failed to start")
        await pool.close()
        return None

    try:
        # Bring the configured store to head (advisory-locked, no-op when current).
        await asyncio.to_thread(apply_migrations, database_url)
    except MigrationError:
        # Confirmed schema-migration failure on a reachable DB: do not degrade a
        # configured store with a broken schema — fail backend startup loudly.
        logger.exception("Session store migration failed")
        await pool.close()
        raise
    except Exception:
        # Reachability/operational error (e.g. the DB became unreachable during the
        # revision check): degrade to 503 rather than crash.
        logger.exception("Session store unreachable during migration check")
        await pool.close()
        return None

    listener = SessionEventListener(database_url, app.state.session_event_hub)
    try:
        await listener.start()
    except Exception:
        logger.exception("Session event listener failed to start")
        await listener.aclose()
        await pool.close()
        return None

    app.state.session_pool = pool
    app.state.session_event_listener = listener
    return pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s", app.title)
    session_pool = None
    session_listener = None
    shared_proxy_manager = None
    shared_proxy_unavailable_reason = None
    app.state.session_event_hub = SessionEventHub()
    app.state.session_pool = None
    app.state.session_event_listener = None
    app.state.shared_proxy_manager = None
    pending_shared_proxy_manager = SharedProxyManager.create(
        runtime_dir=get_settings().storage_dir / "runtime" / "shared-proxy",
    )
    pending_shared_proxy_manager_closed = False
    try:
        try:
            database_url = resolve_database_url(get_settings())
        except MissingDatabaseConfigError as exc:
            logger.info("Session store disabled: %s", exc)
        else:
            session_pool = await _start_session_store(app, database_url)
            session_listener = app.state.session_event_listener
            if session_pool is not None:
                try:
                    await pending_shared_proxy_manager.start()
                except Exception as exc:
                    logger.exception("Shared proxy failed to start; canvas runs disabled")
                    shared_proxy_unavailable_reason = str(exc)
                    await _close_lifespan_resource(
                        "shared proxy manager",
                        pending_shared_proxy_manager.close,
                    )
                    pending_shared_proxy_manager_closed = True
                else:
                    shared_proxy_manager = pending_shared_proxy_manager
                    app.state.shared_proxy_manager = shared_proxy_manager
        app.state.run_manager = run_routes.create_run_manager(
            shared_proxy_manager=shared_proxy_manager,
            shared_proxy_unavailable_reason=shared_proxy_unavailable_reason,
        )
        yield
    finally:
        await _close_lifespan_resource("run manager", lambda: run_routes.close_run_manager(app))
        if not pending_shared_proxy_manager_closed:
            await _close_lifespan_resource(
                "shared proxy manager",
                pending_shared_proxy_manager.close,
            )
        if session_listener is not None:
            await _close_lifespan_resource("session event listener", session_listener.aclose)
        if session_pool is not None:
            await _close_lifespan_resource("session pool", session_pool.close)
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

    # Added after CORS so it wraps it (outermost runs first): every request,
    # HTTP and WebSocket, must carry a trusted Host before anything else sees
    # it. This is the DNS rebinding defense; see Settings.trusted_hosts.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router, prefix="/api")
    app.include_router(run_routes.router, prefix="/v1", tags=["runs"])
    app.include_router(
        exchanges.run_router,
        prefix="/v1" + exchanges.RUN_EXCHANGES_ROUTE_PREFIX,
        tags=["exchanges"],
    )
    app.include_router(meta.run_router, prefix="/v1/runs/{run_id}/meta", tags=["meta"])
    app.include_router(stream.router, prefix="/v1", tags=["stream"])
    app.include_router(session_routes.router, prefix="/v1", tags=["sessions"])

    from pathlib import Path

    www_dir = Path(__file__).parent / "www"
    if www_dir.exists():
        app.mount("/", SpaStaticFiles(directory=www_dir, html=True), name="www")

    return app


async def _close_lifespan_resource(name: str, close: Callable[[], Awaitable[object]]) -> None:
    try:
        await close()
    except Exception:
        logger.exception("Failed to close %s", name)


def __getattr__(name: str) -> object:
    # Build the ASGI ``app`` lazily so importing this module (e.g. at test collection, or
    # by any module that imports create_app/lifespan) does NOT call create_app() ->
    # Settings.load() and read the operator's settings.toml. The server resolves
    # ``transport_matters.main:app`` via getattr at startup, after the environment
    # (TRANSPORT_MATTERS_HOME, DATABASE_URL, ...) is in place.
    if name == "app":
        return create_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
