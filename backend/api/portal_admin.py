"""The owner's side of the family portal (ADR 0007): turn it on or off, choose who may use it, and
make each person a single-use join link. Reading needs system:view, changing system:config;
turning it on is confirmed first and written to the security log."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend import settings
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import logger
from backend.confirmations import confirm_or_raise
from backend.services import family_portal

router = APIRouter(tags=["Network"])


class PortalUpdate(BaseModel):
    on: bool


class PersonUpdate(BaseModel):
    allowed: bool


def _log(action: str, principal: AuthenticatedPrincipal, details: dict[str, Any]) -> None:
    from backend.users_db import log_security_event

    try:
        log_security_event(action, "success", actor_username=principal.username or None, details=details)
    except (OSError, ValueError):
        logger.warning("[Portal] could not write %s to the security log", action, exc_info=True)


def _person(user_id: str) -> dict[str, Any]:
    user = family_portal.active_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="No such active person.")
    return user


@router.get("/network/family-portal", dependencies=[Depends(require_scope("system:view"))])
async def get_portal() -> dict[str, Any]:
    return await asyncio.to_thread(family_portal.owner_view)


@router.put("/network/family-portal", dependencies=[Depends(require_scope("system:config"))])
async def put_portal(
    req: PortalUpdate, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """On (confirmed first: 428 until then) publishes /portal through Funnel; off takes it down."""
    if not req.on:
        out = await asyncio.to_thread(family_portal.unpublish)
        _log("family_portal.off", principal, {"ok": out["ok"]})
        return {**out, **await asyncio.to_thread(family_portal.owner_view)}
    view = await asyncio.to_thread(family_portal.owner_view)
    if view["immich_moves_to"]:
        confirm_or_raise(request, principal, "network.family_portal_move_immich", view["immich_moves_to"])
    else:
        confirm_or_raise(request, principal, "network.family_portal", view["address"] or "/portal")
    out = await asyncio.to_thread(
        family_portal.publish, int(settings.current("port") or 8082), bool(view["immich_moves_to"])
    )
    _log("family_portal.on", principal, {"ok": out["ok"], "address": view["address"]})
    return {**out, **await asyncio.to_thread(family_portal.owner_view)}


@router.put("/network/family-portal/people/{user_id}", dependencies=[Depends(require_scope("system:config"))])
async def put_person(
    user_id: str, req: PersonUpdate, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    _person(user_id)
    await asyncio.to_thread(family_portal.allow, user_id, req.allowed)
    _log("family_portal.person", principal, {"user_id": user_id, "allowed": req.allowed})
    return await asyncio.to_thread(family_portal.owner_view)


@router.post("/network/family-portal/people/{user_id}/invite", dependencies=[Depends(require_scope("system:config"))])
async def post_invite(
    user_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """A single-use join link (7 days). The token travels after # so it never reaches a server log."""
    _person(user_id)
    try:
        token = await asyncio.to_thread(family_portal.make_invite, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    base = await asyncio.to_thread(family_portal.address)
    _log("family_portal.invite", principal, {"user_id": user_id})
    return {"link": f"{base}#join={token}" if base else "", "token": token, "days": family_portal.INVITE_SECS // 86400}


@router.delete("/network/family-portal/people/{user_id}/invite", dependencies=[Depends(require_scope("system:config"))])
async def delete_invite(user_id: str) -> dict[str, Any]:
    await asyncio.to_thread(family_portal.withdraw_invite, user_id)
    return await asyncio.to_thread(family_portal.owner_view)
