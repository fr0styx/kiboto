"""SNMP v3 agent settings, off by default (owner decision, 16 Nov 2026). See backend/services/snmp_agent.py."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import confirm_or_raise
from backend.services import snmp_agent

router = APIRouter(tags=["Network & Switching"])


class SnmpIn(BaseModel):
    enabled: bool = False
    port: int = Field(snmp_agent.DEFAULT_PORT, ge=1, le=65535)
    user: str = Field("", max_length=32)
    auth_password: str | None = Field(None, max_length=128, description="None keeps the stored password")
    priv_password: str | None = Field(None, max_length=128, description="None keeps the stored password")
    contact: str = Field("", max_length=255)
    location: str = Field("", max_length=255)


@router.get("/network/snmp", dependencies=[Depends(require_scope("system:view"))])
def get_snmp() -> dict[str, Any]:
    return snmp_agent.public_state()


@router.put("/network/snmp", dependencies=[Depends(require_scope("system:config"))])
async def put_snmp(
    req: SnmpIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Saves the settings; turning the agent on is confirmed first (428 until then): it opens a
    port on the home network."""
    if req.enabled and not snmp_agent.public_state()["enabled"]:
        confirm_or_raise(request, principal, "network.snmp", f"UDP {req.port}")
    try:
        return await asyncio.to_thread(
            snmp_agent.save,
            req.enabled,
            req.port,
            req.user,
            req.auth_password,
            req.priv_password,
            req.contact,
            req.location,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
