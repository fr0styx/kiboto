"""Host firewall settings (audit A13). See backend/services/firewall.py."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.auth import require_scope
from backend.errors import ApiError
from backend.services import firewall

router = APIRouter(tags=["Security"])


class FirewallIn(BaseModel):
    enabled: bool = False
    outside: dict[str, bool] = {}  # what the outside reaches; the home network reaches everything


def _out(st: dict[str, Any]) -> dict[str, Any]:
    possible, why = firewall.capability()
    v4, v6 = firewall.home()
    return {
        **st,
        "possible": possible,
        "why_not": why,
        "home": [*v4, *v6],
        "rules": firewall.ruleset({**st, "enabled": True}),
    }


@router.get("/security/firewall", dependencies=[Depends(require_scope("system:view"))])
def get_firewall() -> dict[str, Any]:
    return _out(firewall.state())


@router.put("/security/firewall", dependencies=[Depends(require_scope("system:config"))])
def put_firewall(req: FirewallIn, request: Request) -> dict[str, Any]:
    # the address the connection itself comes from (a reverse proxy's, not its visitor's): that is
    # what the rules will see
    peer = request.client.host if request.client else ""
    try:
        return _out(firewall.save(req.enabled, req.outside, asked_from=peer))
    except ValueError as e:
        raise ApiError(400, str(e), "invalid_settings", text=getattr(e, "text", None)) from e
    except RuntimeError as e:
        raise ApiError(502, str(e), "firewall_not_loaded") from e
