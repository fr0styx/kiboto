"""Switch off when too hot (see backend/services/heat_guard.py); off by default."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth import require_scope
from backend.services import heat_guard

router = APIRouter(tags=["System"])


class HeatShutdownIn(BaseModel):
    enabled: bool = False


@router.get("/system/heat-shutdown", dependencies=[Depends(require_scope("system:view"))])
def get_heat_shutdown() -> dict[str, Any]:
    return heat_guard.public_state()


@router.put("/system/heat-shutdown", dependencies=[Depends(require_scope("system:power"))])
def put_heat_shutdown(req: HeatShutdownIn) -> dict[str, Any]:
    return heat_guard.set_enabled(req.enabled)
