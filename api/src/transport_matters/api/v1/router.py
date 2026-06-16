from fastapi import APIRouter

from transport_matters.api.v1 import (
    breakpoint_routes,
    capabilities,
    local_file_routes,
    meta,
    overrides,
    terminal,
)

api_router = APIRouter()
api_router.include_router(overrides.router, prefix="/overrides", tags=["overrides"])
api_router.include_router(breakpoint_routes.router, prefix="/breakpoint", tags=["breakpoint"])
api_router.include_router(meta.router, prefix="/meta", tags=["meta"])
api_router.include_router(local_file_routes.router, tags=["local-file"])
api_router.include_router(terminal.router, tags=["terminal"])
api_router.include_router(capabilities.router, tags=["capabilities"])
