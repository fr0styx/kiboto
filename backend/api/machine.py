"""The machine itself, where Kiboto is its interface: the clock and the SSH switch."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend import machine_key
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


# --- the data key and its recovery key -----------------------------------------------------------
class RecoveryKeyIn(BaseModel):
    recovery_key: str = Field(min_length=1, max_length=64)


def _key_or_404() -> None:
    if not machine_key.active():
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/system/machine/key", dependencies=[Depends(require_scope("system:config"))])
async def get_machine_key() -> dict[str, Any]:
    """Whether this machine keeps its data key sealed to itself, to what (its security chip or its
    system disk), whether it could open it, and whether the recovery key still has to be written
    down. Never a key. Where Kiboto is a guest only `managed: false`."""
    return await asyncio.to_thread(machine_key.status)


@router.post("/system/machine/key/recovery-key", dependencies=[Depends(require_scope("system:config"))])
async def show_recovery_key() -> dict[str, Any]:
    """The recovery key, while it is waiting to be written down (409 afterwards: Kiboto no longer has it)."""
    _key_or_404()
    key = await asyncio.to_thread(machine_key.recovery_key_to_write_down)
    if not key:
        raise HTTPException(status_code=409, detail="The recovery key was written down; Kiboto no longer has it.")
    return {"recovery_key": key}


@router.post("/system/machine/key/written-down", dependencies=[Depends(require_scope("system:config"))])
async def recovery_key_written_down() -> dict[str, Any]:
    """The person has the recovery key: Kiboto forgets it."""
    _key_or_404()
    await asyncio.to_thread(machine_key.written_down)
    return await asyncio.to_thread(machine_key.status)


@router.post("/system/machine/key/unlock", dependencies=[Depends(require_scope("system:config"))])
async def unlock_machine_key(req: RecoveryKeyIn) -> dict[str, Any]:
    """Opens the data key with the recovery key after a new board or a restored system, seals it to
    the machine as it is now, and starts Kiboto again so the AI data opens."""
    _key_or_404()
    try:
        await asyncio.to_thread(machine_key.unlock, req.recovery_key)
    except machine_key.MachineKeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    restarting = await asyncio.to_thread(host_basics.restart_kiboto)
    return {**await asyncio.to_thread(machine_key.status), "restarting": restarting}


@router.post("/system/machine/key/new-recovery-key", dependencies=[Depends(require_scope("system:config"))])
async def new_recovery_key(
    request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Makes a new recovery key; the one before stops working. Confirmed first (428 until then)."""
    _key_or_404()
    confirm_or_raise(request, principal, "system.new_recovery_key", host_basics.host_name())
    try:
        await asyncio.to_thread(machine_key.renew_recovery_key)
    except machine_key.MachineKeyError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    return await asyncio.to_thread(machine_key.status)


# --- the settings copy on the pools ----------------------------------------------------------------
@router.get("/system/settings-copy", dependencies=[Depends(require_scope("system:config"))])
async def get_settings_copy() -> dict[str, Any]:
    """Per pool, when the copy of Kiboto's settings on it was last written and whether the last
    try failed. No pool is touched to answer. Where Kiboto is a guest only `managed: false`."""
    from backend.services import pool_copy

    return await asyncio.to_thread(pool_copy.status)


@router.post("/system/settings-copy/now", dependencies=[Depends(require_scope("system:config"))])
async def copy_settings_now() -> dict[str, Any]:
    """Writes the copy now to every pool whose drives are awake; a sleeping pool is left asleep
    and keeps the copy it has. Says per pool what happened."""
    from backend.services import pool_copy

    if not machine_key.active():
        raise HTTPException(status_code=404, detail="Not found")
    done = await asyncio.to_thread(pool_copy.copy_if_due, None, True)
    return {**await asyncio.to_thread(pool_copy.status), "done": done}


class SettingsRestoreIn(BaseModel):
    key: str = Field(min_length=3, max_length=64)
    recovery_key: str = Field(min_length=1, max_length=64)


@router.get("/system/settings-copy/found", dependencies=[Depends(require_scope("system:config"))])
async def get_found_settings() -> dict[str, Any]:
    """The settings of other installs that the last look found on the drives. No drive is touched."""
    from backend.services import pool_copy

    return {"found": await asyncio.to_thread(pool_copy.found)}


@router.post("/system/settings-copy/look", dependencies=[Depends(require_scope("system:config"))])
async def look_for_settings() -> dict[str, Any]:
    """Looks on every pool, in use or not, for the settings an earlier Kiboto left there. Reads the
    drives, so it wakes them. Pools this system does not use are opened read-only and closed again."""
    from backend.services import pool_copy

    if not machine_key.active():
        raise HTTPException(status_code=404, detail="Not found")
    return {"found": await asyncio.to_thread(pool_copy.look)}


@router.post("/system/settings-copy/restore", dependencies=[Depends(require_scope("system:config"))])
async def restore_found_settings(req: SettingsRestoreIn) -> dict[str, Any]:
    """Brings back the settings of a found copy with the recovery key of the install that wrote it,
    and starts Kiboto again. The settings this install has now are saved first."""
    from backend.services import pool_copy

    if not machine_key.active():
        raise HTTPException(status_code=404, detail="Not found")
    try:
        done = await asyncio.to_thread(pool_copy.restore, req.key, req.recovery_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return {**done, "restarting": await asyncio.to_thread(host_basics.restart_kiboto)}
