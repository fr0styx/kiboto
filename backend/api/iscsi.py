"""Disks for other computers over iSCSI (owner's decision, 19 Nov 2026): off until turned on.

For whoever manages the storage. Turning it on, saving a disk (the service restarts, which cuts
off a computer that is using one for a moment) and removing a disk are each confirmed."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import confirm_or_raise, require_confirmation
from backend.errors import ApiError, said
from backend.services import iscsi_target

router = APIRouter(tags=["iSCSI"])
ADMIN = Depends(require_scope("storage:admin"))


class DiskIn(BaseModel):
    name: str = Field("", max_length=64)
    size_gb: int
    folder: str = Field("", max_length=4096)
    user: str = Field(..., max_length=64)
    secret: str = Field("", max_length=64)
    allow: str = Field("", max_length=64)


class SwitchIn(BaseModel):
    enabled: bool


def _refused(e: iscsi_target.DiskError) -> ApiError:
    return ApiError(400, str(e), f"iscsi_{e.key}", text=said(f"iscsi_{e.key}", **e.params))


def _missing() -> ApiError:
    return ApiError(404, "There is no such disk.", "iscsi_not_found", text=said("iscsi_not_found"))


def _note(principal: AuthenticatedPrincipal, request: Request, what: str, **details: Any) -> None:
    from backend.users_db import log_security_event

    log_security_event(
        f"iscsi.{what}",
        "success",
        actor_id=getattr(principal, "user_id", None),
        actor_username=principal.username,
        actor_ip=request.client.host if request.client else "",
        details=details,
    )


@router.get("/iscsi", dependencies=[ADMIN])
async def iscsi_view() -> dict[str, Any]:
    """Whether the service is on and running, and the disks (never their passwords), and what the
    feature table says of iSCSI on this edition."""
    from backend.services import edition_features

    return {**await asyncio.to_thread(iscsi_target.status), "edition": edition_features.state("iscsi")}


@router.put("/iscsi/enabled", dependencies=[ADMIN])
async def iscsi_switch(
    req: SwitchIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Turns the service on or off. Turning it on asks for confirmation; off never does."""
    if req.enabled and not iscsi_target.enabled():
        confirm_or_raise(request, principal, "iscsi.enable")
    iscsi_target.set_enabled(req.enabled)
    _note(principal, request, "switch", enabled=req.enabled)
    return await asyncio.to_thread(iscsi_target.ensure)


@router.post("/iscsi/disks", dependencies=[ADMIN, Depends(require_confirmation("iscsi.save"))])
async def iscsi_add(
    req: DiskIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Adds a disk: makes its file in the folder (it takes no space until it is written to)."""
    try:
        made = await asyncio.to_thread(iscsi_target.save, req.model_dump())
    except iscsi_target.DiskError as e:
        raise _refused(e) from e
    _note(principal, request, "save", disk=made["name"], new=True, size_gb=made["size_gb"], folder=made["folder"])
    return await asyncio.to_thread(iscsi_target.ensure)


@router.put("/iscsi/disks/{disk_id}", dependencies=[ADMIN, Depends(require_confirmation("iscsi.save"))])
async def iscsi_change(
    disk_id: str,
    req: DiskIn,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Changes a disk: a larger size, another user name or password, another allowed address."""
    try:
        made = await asyncio.to_thread(iscsi_target.save, req.model_dump(), disk_id)
    except iscsi_target.DiskError as e:
        raise _refused(e) from e
    except KeyError:
        raise _missing() from None
    _note(principal, request, "save", disk=made["name"], new=False, size_gb=made["size_gb"], folder=made["folder"])
    return await asyncio.to_thread(iscsi_target.ensure)


@router.delete("/iscsi/disks/{disk_id}", dependencies=[ADMIN, Depends(require_confirmation("iscsi.delete"))])
async def iscsi_remove(
    disk_id: str,
    request: Request,
    with_file: bool = False,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Takes a disk off the list. Its file is kept unless with_file is true."""
    gone = await asyncio.to_thread(iscsi_target.delete, disk_id, with_file)
    if gone is None:
        raise _missing()
    _note(principal, request, "delete", disk=gone["name"], with_file=with_file)
    return await asyncio.to_thread(iscsi_target.ensure)
