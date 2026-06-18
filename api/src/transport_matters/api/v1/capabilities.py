"""Capability endpoint for local managed harness availability."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from transport_matters.capabilities import HarnessCapability, HarnessName, detect_harnesses

router = APIRouter()


class HarnessCapabilityResponse(BaseModel):
    installed: bool
    path: str | None
    version: str | None

    @classmethod
    def from_core(cls, capability: HarnessCapability) -> HarnessCapabilityResponse:
        return cls(
            installed=capability.installed,
            path=capability.path,
            version=capability.version,
        )


class CapabilitiesResponse(BaseModel):
    harnesses: dict[HarnessName, HarnessCapabilityResponse]


@router.get("/capabilities")
async def get_capabilities() -> CapabilitiesResponse:
    harnesses = await asyncio.to_thread(detect_harnesses)
    return CapabilitiesResponse(
        harnesses={
            name: HarnessCapabilityResponse.from_core(capability)
            for name, capability in harnesses.items()
        }
    )
