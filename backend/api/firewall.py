"""Host firewall settings (audit A13). See backend/services/firewall.py."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.services import firewall

router = APIRouter(tags=["Security"])


class FirewallIn(BaseModel):
    enabled: bool = False
    allow_from: str = Field("lan", pattern="^(lan|anywhere)$")
    services: dict[str, bool] = {}


def _out(st: dict[str, Any]) -> dict[str, Any]:
    possible, why = firewall.capability()
    return {**st, "possible": possible, "why_not": why, "rules": firewall.ruleset({**st, "enabled": True})}


@router.get("/security/firewall", dependencies=[Depends(require_scope("system:view"))])
def get_firewall() -> dict[str, Any]:
    return _out(firewall.state())


@router.put("/security/firewall", dependencies=[Depends(require_scope("system:config"))])
def put_firewall(req: FirewallIn) -> dict[str, Any]:
    try:
        return _out(firewall.save(req.enabled, req.allow_from, req.services))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
