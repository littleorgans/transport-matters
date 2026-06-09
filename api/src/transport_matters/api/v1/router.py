from fastapi import APIRouter

from transport_matters.api.v1 import (
    breakpoint_routes,
    captured_terminal,
    exchanges,
    meta,
    overrides,
    session_routes,
    stream,
    terminal,
)

api_router = APIRouter()
api_router.include_router(
    exchanges.router, prefix=exchanges.EXCHANGES_ROUTE_PREFIX, tags=["exchanges"]
)
api_router.include_router(overrides.router, prefix="/overrides", tags=["overrides"])
api_router.include_router(breakpoint_routes.router, prefix="/breakpoint", tags=["breakpoint"])
api_router.include_router(meta.router, prefix="/meta", tags=["meta"])
api_router.include_router(session_routes.router, tags=["sessions"])
api_router.include_router(stream.router, tags=["stream"])
api_router.include_router(terminal.router, tags=["terminal"])
api_router.include_router(captured_terminal.router, tags=["captured-terminal"])
