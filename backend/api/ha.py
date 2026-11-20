"""High availability (the owner's decisions of 19 Nov 2026): the link between two Kiboto boxes.

The owner's routes need the right to change the system; pairing and unpairing are confirmed. The
two routes the other box calls need no sign-in: pairing is proved with the one-time pairing key,
and every later message is sealed with the key the two boxes share."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import confirm_or_raise, require_confirmation
from backend.errors import ApiError, said
from backend.rate_limit import rate_limit
from backend.services import ha_link, ha_state

router = APIRouter(tags=["High availability"])
ADMIN = Depends(require_scope("system:config"))


class PairIn(BaseModel):
    address: str = Field(min_length=8, max_length=255)  # the first NAS
    code: str = Field(min_length=16, max_length=40)
    my_address: str = Field(min_length=8, max_length=255)  # where the first NAS reaches this one


class PeerPairIn(BaseModel):
    box_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    name: str = Field(max_length=128)
    address: str = Field(min_length=8, max_length=255)
    public: str = Field(min_length=40, max_length=64)
    proof: str = Field(pattern=r"^[a-f0-9]{64}$")


class EnvelopeIn(BaseModel):
    sender: str = Field(alias="from", pattern=r"^[a-f0-9]{16}$")
    n: str = Field(min_length=16, max_length=24)
    c: str = Field(min_length=24, max_length=12_000_000)


def _refused(e: ha_link.LinkError, status: int = 400) -> ApiError:
    return ApiError(status, str(e), f"ha_{e.key}", text=said(f"ha_{e.key}"))


def _actor(principal: AuthenticatedPrincipal) -> str:
    return getattr(principal, "username", "") or ""


def _status() -> dict[str, Any]:
    """The link's status, and the copy of people and settings that goes with it."""
    return {**ha_link.status(), **ha_state.view()}


@router.get("/ha", dependencies=[ADMIN])
async def ha_status() -> dict[str, Any]:
    """This box's part (first, second or none), the other box, how the last contact went, and
    the copy of the first NAS's people and settings the second one keeps."""
    return await asyncio.to_thread(_status)


@router.post("/ha/code", dependencies=[ADMIN])
async def ha_code(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """On the first NAS: a pairing key to type into the second one. Shown once, good for ten minutes."""
    try:
        return await asyncio.to_thread(ha_link.new_code, _actor(principal))
    except ha_link.LinkError as e:
        raise _refused(e, 409) from e


@router.post("/ha/pair", dependencies=[ADMIN])
async def ha_pair(
    req: PairIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """On the second NAS: pairs with the first one, using the pairing key shown there. Confirmed."""
    try:
        target = ha_link.clean_address(req.address)
    except ha_link.LinkError as e:
        raise _refused(e) from e
    confirm_or_raise(request, principal, "ha.pair", target=target)
    try:
        await asyncio.to_thread(ha_link.pair_with, target, req.code, req.my_address, _actor(principal))
    except ha_link.LinkError as e:
        raise _refused(e, 409 if e.key in ("paired", "unreachable", "refused") else 400) from e
    await asyncio.to_thread(ha_state.fetch_soon)  # the first copy of people and settings, right away
    return await asyncio.to_thread(_status)


@router.delete("/ha", dependencies=[ADMIN, Depends(require_confirmation("ha.unpair"))])
async def ha_unpair(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """Forgets the other box and the copy kept of it, and tells it to forget this one when it can be reached."""
    await asyncio.to_thread(ha_link.unpair, _actor(principal))
    return await asyncio.to_thread(_status)


@router.post("/ha/check", dependencies=[ADMIN])
async def ha_check() -> dict[str, Any]:
    """Asks the other box whether it is there."""
    await asyncio.to_thread(ha_link.check)
    return await asyncio.to_thread(_status)


@router.post("/ha/fetch", dependencies=[ADMIN])
async def ha_fetch() -> dict[str, Any]:
    """On the second NAS: fetches the first one's people and settings now (it also does every night)."""
    if ha_link.role() != "second":
        raise _refused(ha_link.LinkError("not_second", "Only the second NAS fetches people and settings."), 409)
    await asyncio.to_thread(ha_state.fetch_soon)
    return await asyncio.to_thread(_status)


@router.post("/ha/peer/pair", dependencies=[Depends(rate_limit("ha.pair", 10, 600, per="ip"))])
async def ha_peer_pair(req: PeerPairIn) -> dict[str, Any]:
    """The second NAS pairs with this one: it proves that it has the pairing key shown here."""
    try:
        return await asyncio.to_thread(ha_link.accept_pairing, req.box_id, req.name, req.address, req.public, req.proof)
    except ha_link.LinkError as e:
        raise _refused(e, 403) from e


@router.post("/ha/peer/call", dependencies=[Depends(rate_limit("ha.peer", 240, 60, per="ip"))])
async def ha_peer_call(req: EnvelopeIn) -> dict[str, str]:
    """A sealed message from the paired box; the answer is sealed too."""
    try:
        return await asyncio.to_thread(ha_link.handle_call, {"from": req.sender, "n": req.n, "c": req.c})
    except ha_link.LinkError as e:
        raise _refused(e, 403) from e
