"""The machine itself, where Kiboto is its interface: the clock and the SSH switch."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import confirm_or_raise
from backend.services import host_basics

router = APIRouter(tags=["System"])


class MachineUpdate(BaseModel):
    ssh: bool | None = None
    clock_automatic: bool | None = None


@router.get("/system/machine", dependencies=[Depends(require_scope("system:config"))])
async def get_machine() -> dict[str, Any]:
    """On a machine set up for Kiboto: its name and time zone, whether its clock is set from the
    internet and whether SSH takes sign-ins. Elsewhere only `managed: false`: these belong to the host.
    An administrator's set-up, so only an administrator reads it."""
    return await asyncio.to_thread(host_basics.status)


@router.put("/system/machine", dependencies=[Depends(require_scope("system:config"))])
async def put_machine(
    req: MachineUpdate, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Turns SSH or setting the clock from the internet on or off. Turning SSH on is confirmed
    first (428 until then): it opens the machine's command line to the network."""
    now = await asyncio.to_thread(host_basics.status)
    if not now["managed"]:
        raise HTTPException(status_code=409, detail="These settings belong to the system Kiboto runs on.")
    if req.ssh and not now["ssh"]["on"]:
        confirm_or_raise(request, principal, "system.ssh_on", str(now["host_name"]))
    done = True
    if req.ssh is not None:
        done = await asyncio.to_thread(host_basics.set_ssh, req.ssh) and done
    if req.clock_automatic is not None:
        done = await asyncio.to_thread(host_basics.set_clock_automatic, req.clock_automatic) and done
    if not done:
        raise HTTPException(status_code=502, detail="The machine did not take the change.")
    return await asyncio.to_thread(host_basics.status)
