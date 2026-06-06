from fastapi import APIRouter

from transport_matters.api.v1 import (
    breakpoint_routes,
    exchanges,
    index_routes,
    meta,
    overrides,
    session_routes,
    stream,
)

api_router = APIRouter()
api_router.include_router(exchanges.router, prefix="/exchanges", tags=["exchanges"])
api_router.include_router(overrides.router, prefix="/overrides", tags=["overrides"])
api_router.include_router(breakpoint_routes.router, prefix="/breakpoint", tags=["breakpoint"])
api_router.include_router(meta.router, prefix="/meta", tags=["meta"])
api_router.include_router(index_routes.router, prefix="/index", tags=["index"])
api_router.include_router(session_routes.router, tags=["sessions"])
api_router.include_router(stream.router, tags=["stream"])
