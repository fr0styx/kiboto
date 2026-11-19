"""The check for a new drive (owner's decision, 19 Nov 2026): started by hand, read-only, and only on
a drive that is not in use. Starting it is confirmed: it keeps the drive awake and busy for hours."""

from typing import Any

from fastapi import APIRouter, Depends, Path

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import require_confirmation
from backend.errors import ApiError, said
from backend.services import drive_check

router = APIRouter(tags=["Drive Health"])
DEV = Path(..., pattern=r"^(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)$")


@router.get("/drives/check", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def drive_checks() -> dict[str, Any]:
    """Every drive with whether it may be checked, the check that is going, and its last result.
    Never wakes a drive."""
    return drive_check.view()


@router.post(
    "/drives/{dev}/check",
    dependencies=[Depends(require_scope("storage:admin")), Depends(require_confirmation("disk.surface_check"))],
)
def start_drive_check(
    dev: str = DEV, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Starts reading the whole surface of a drive that is not in use. It only reads."""
    try:
        return {"status": "started", "check": drive_check.start(dev, principal.username or "")}
    except drive_check.NotNow as e:
        raise ApiError(409, str(e), f"drive_check_{e.key}", text=said(f"drive_check_{e.key}")) from e


@router.post("/drives/{dev}/check/stop", dependencies=[Depends(require_scope("storage:admin"))])
def stop_drive_check(dev: str = DEV) -> dict[str, Any]:
    """Stops a check that is going. What it found so far is kept as an unfinished result."""
    return {"stopped": drive_check.stop(dev)}
