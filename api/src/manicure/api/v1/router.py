from fastapi import APIRouter

from manicure.api.v1 import exchanges, rules, stream

api_router = APIRouter()
api_router.include_router(exchanges.router, prefix="/exchanges", tags=["exchanges"])
api_router.include_router(rules.router, prefix="/rules", tags=["rules"])
api_router.include_router(stream.router, tags=["stream"])
