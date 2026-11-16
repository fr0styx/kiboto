"""Dynamic DNS settings and its 5-minute loop (audit A8). See backend/services/ddns.py."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.config import logger
from backend.services import ddns

router = APIRouter(tags=["Network & Switching"])
LOOK_EVERY_SECS = 60


class DdnsIn(BaseModel):
    enabled: bool = False
    provider: str = Field("duckdns", pattern="^(duckdns|cloudflare)$")
    hostname: str = Field("", max_length=253)
    token: str | None = Field(
        None, max_length=512, description="None keeps the stored token; an empty string clears it"
    )


@router.get("/network/ddns", dependencies=[Depends(require_scope("system:view"))])
def get_ddns() -> dict[str, Any]:
    return ddns.public_state()


@router.put("/network/ddns", dependencies=[Depends(require_scope("system:config"))])
def put_ddns(req: DdnsIn) -> dict[str, Any]:
    try:
        return ddns.save(req.enabled, req.provider, req.hostname, req.token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/network/ddns/update", dependencies=[Depends(require_scope("system:config"))])
async def update_ddns_now() -> dict[str, Any]:
    return await asyncio.to_thread(ddns.run_once)


async def ddns_loop() -> None:
    """Every minute, run an update when one is due (only while Dynamic DNS is on)."""
    while True:
        try:
            if ddns.due(time.time()):
                await asyncio.to_thread(ddns.run_once)
        except (OSError, ValueError) as e:  # the loop outlives a bad file or a provider outage
            logger.warning("Dynamic DNS update failed: %s", e)
        await asyncio.sleep(LOOK_EVERY_SECS)
