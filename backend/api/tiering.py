"""Data tiering (owner's decision, 19 Nov 2026): files nobody opens move to the slow pool at night.

For whoever manages the storage. Off for every shared folder until turned on, which is confirmed;
so is moving a folder's old files now instead of at night, because it wakes the hard drives."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import confirm_or_raise, require_confirmation
from backend.errors import ApiError, said
from backend.services import tiering

router = APIRouter(tags=["Tiering"])
ADMIN = Depends(require_scope("storage:admin"))


class FolderIn(BaseModel):
    enabled: bool
    days: int = Field(tiering.DEFAULT_DAYS)
    slow: str = Field("", max_length=128)  # on one of Kiboto's own pools: the pool its old files move to


def _refused(e: tiering.NotNow) -> ApiError:
    status = 409 if e.key in ("busy", "merge_failed") else 404 if e.key == "no_folder" else 400
    return ApiError(status, str(e), f"tiering_{e.key}", text=said(f"tiering_{e.key}", **e.params))


def _note(principal: AuthenticatedPrincipal, request: Request, what: str, **details: Any) -> None:
    from backend.users_db import log_security_event

    log_security_event(
        f"tiering.{what}",
        "success",
        actor_id=getattr(principal, "user_id", None),
        actor_username=principal.username,
        actor_ip=request.client.host if request.client else "",
        details=details,
    )


@router.get("/tiering", dependencies=[ADMIN])
async def tiering_view() -> dict[str, Any]:
    """Each shared folder: whether tiering fits it, whether it is on, and how its last run went; and
    what the feature table says of merged folders on this edition."""
    from backend.services import edition_features

    return {**await asyncio.to_thread(tiering.view), "edition": edition_features.state("merged_folders")}


@router.put("/tiering/folders/{name}", dependencies=[ADMIN])
async def tiering_set(
    name: str, req: FolderIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Turns tiering on for a shared folder (confirmed), changes its days, or turns it off. On one
    of Kiboto's own pools turning it on makes the folder a merged one, which is confirmed in its own words."""
    if req.enabled and tiering.get(name) is None:
        fits = await asyncio.to_thread(tiering.candidates)
        fit = next((c for c in fits if c["name"] == name), {})
        becomes_merged = fit.get("kind") == "merged" and not fit.get("slow_pool")
        confirm_or_raise(request, principal, "tiering.merge" if becomes_merged else "tiering.enable", target=name)
    try:
        await asyncio.to_thread(tiering.set_folder, name, req.enabled, req.days, None, req.slow)
    except tiering.NotNow as e:
        raise _refused(e) from e
    _note(principal, request, "set", folder=name, enabled=req.enabled, days=req.days if req.enabled else None)
    await asyncio.to_thread(tiering.watch)
    return await asyncio.to_thread(tiering.view)


@router.post("/tiering/folders/{name}/run", dependencies=[ADMIN, Depends(require_confirmation("tiering.run"))])
async def tiering_run(
    name: str, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Moves the folder's old files now. Returns at once; the view shows when it has ended."""
    try:
        await asyncio.to_thread(tiering.run_soon, name)
    except tiering.NotNow as e:
        raise _refused(e) from e
    _note(principal, request, "run", folder=name)
    return await asyncio.to_thread(tiering.view)
