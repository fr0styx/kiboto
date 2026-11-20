"""High availability (the owner's decisions of 19 Nov 2026): the link between two Kiboto boxes.

The owner's routes need the right to change the system; pairing and unpairing are confirmed. The
two routes the other box calls need no sign-in: pairing is proved with the one-time pairing key,
and every later message is sealed with the key the two boxes share."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import confirm_or_raise, require_confirmation
from backend.errors import ApiError, said
from backend.rate_limit import rate_limit
from backend.services import ha_folders, ha_link, ha_state, ha_takeover

router = APIRouter(tags=["High availability"])
ADMIN = Depends(require_scope("system:config"))


class PairIn(BaseModel):
    address: str = Field(min_length=8, max_length=255)  # the first NAS
    code: str = Field(min_length=16, max_length=40)
    my_address: str = Field(min_length=8, max_length=255)  # where the first NAS reaches this one


class FoldersIn(BaseModel):
    names: list[str] = Field(max_length=64)


class TakeoverIn(BaseModel):
    even_if_answering: bool = False
    # what else comes along, switched off: "backups" (the first NAS's backups of the kept folders)
    bring: list[Literal["backups"]] = Field(default_factory=list, max_length=4)


class TakeBackIn(BaseModel):
    even_if_unreachable: bool = False


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
    return {**ha_link.status(), **ha_state.view(), **ha_folders.view(), **ha_takeover.view()}


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


@router.get("/ha/folders", dependencies=[ADMIN])
async def ha_folders_view() -> dict[str, Any]:
    """On the second NAS: the first one's shared folders (asked now), and the ones chosen to be kept."""
    if ha_link.role() != "second":
        raise _refused(ha_link.LinkError("not_second", "Only the second NAS keeps the first one's folders."), 409)
    try:
        there: list[str] | None = await asyncio.to_thread(ha_folders.available)
        error = ""
    except ha_link.LinkError as e:
        there, error = None, e.key
    return {"available": there, "error": error, **ha_folders.view()}


@router.put("/ha/folders", dependencies=[ADMIN])
async def ha_folders_set(
    req: FoldersIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """On the second NAS: which of the first one's folders are kept in step. Confirmed; the first fetch starts at once."""
    names = sorted({n.strip() for n in req.names if n.strip()})
    if names:
        confirm_or_raise(request, principal, "ha.folders", target=", ".join(names))
    try:
        await asyncio.to_thread(ha_folders.choose, names)
    except ha_link.LinkError as e:
        raise _refused(e, 409 if e.key in ("not_second", "unreachable", "refused") else 400) from e
    ha_link.audit("folders", f"folders kept in step: {', '.join(names) or 'none'}", _actor(principal))
    await asyncio.to_thread(ha_state.fetch_soon)
    return await asyncio.to_thread(_status)


@router.post("/ha/takeover", dependencies=[ADMIN])
async def ha_take_over(
    req: TakeoverIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """On the second NAS: it takes the first one's people, their access to the kept folders, and its
    name, and restarts. Refused (409 ha_first_answers) while the first NAS answers, unless asked again
    with even_if_answering. Confirmed either way."""
    first = (ha_link.peer() or {}).get("name") or ""
    confirm_or_raise(
        request, principal, "ha.takeover_anyway" if req.even_if_answering else "ha.takeover", target=str(first)
    )
    try:
        said = await asyncio.to_thread(
            ha_takeover.take_over, _actor(principal), req.even_if_answering, tuple(req.bring)
        )
    except ha_link.LinkError as e:
        raise _refused(e, 400 if e.key == "bad_copy" else 409) from e
    return {**await asyncio.to_thread(_status), "restarting": bool(said.get("restarting"))}


@router.post("/ha/take-back", dependencies=[ADMIN])
async def ha_take_back(
    req: TakeBackIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """On a first NAS that holds its name back: it answers to it again, and the second one stops.
    Refused (409 ha_second_unreachable) when the second NAS cannot be told, unless asked again with
    even_if_unreachable."""
    confirm_or_raise(request, principal, "ha.take_back_anyway" if req.even_if_unreachable else "ha.take_back")
    try:
        await asyncio.to_thread(ha_takeover.take_back, _actor(principal), req.even_if_unreachable)
    except ha_link.LinkError as e:
        raise _refused(e, 409) from e
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
