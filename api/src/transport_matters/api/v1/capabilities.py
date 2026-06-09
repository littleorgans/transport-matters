"""Capability endpoint for local managed CLI availability."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from transport_matters.capabilities import CliCapability, CliName, detect_clis

router = APIRouter()


class CliCapabilityResponse(BaseModel):
    installed: bool
    path: str | None
    version: str | None

    @classmethod
    def from_core(cls, capability: CliCapability) -> CliCapabilityResponse:
        return cls(
            installed=capability.installed,
            path=capability.path,
            version=capability.version,
        )


class CapabilitiesResponse(BaseModel):
    clis: dict[CliName, CliCapabilityResponse]


@router.get("/capabilities")
async def get_capabilities() -> CapabilitiesResponse:
    clis = await asyncio.to_thread(detect_clis)
    return CapabilitiesResponse(
        clis={
            name: CliCapabilityResponse.from_core(capability) for name, capability in clis.items()
        }
    )
