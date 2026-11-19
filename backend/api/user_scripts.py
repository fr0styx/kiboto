"""Scheduled scripts: an administrator's own scripts, run on a timer (owner's decision, 19 Nov 2026).

Every route is for the full administrator only: a script runs with Kiboto's rights. Turning the
feature on and saving a script each ask for confirmation, so a stray request or an AI tool call
cannot plant one."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import confirm_or_raise, require_confirmation
from backend.errors import ApiError, said
from backend.services import user_scripts

router = APIRouter(tags=["Scripts"])
ADMIN = Depends(require_scope("*"))


class ScheduleIn(BaseModel):
    kind: str = "manual"
    at: str | None = Field(default=None, max_length=5)
    minute: int | None = None
    days: list[int] | None = None


class ScriptIn(BaseModel):
    name: str = Field(..., max_length=200)
    body: str = Field(..., max_length=user_scripts.MAX_BODY_BYTES * 2)
    schedule: ScheduleIn = ScheduleIn(kind="manual")
    enabled: bool = True
    limit_folder: str = Field("", max_length=4096)
    timeout_min: int = user_scripts.DEFAULT_TIMEOUT_MIN


class SwitchIn(BaseModel):
    enabled: bool


def _refused(e: Exception, status: int = 400) -> ApiError:
    key = getattr(e, "key", "bad")
    return ApiError(status, str(e), f"script_{key}", text=said(f"script_{key}", **getattr(e, "params", {})))


def _missing() -> ApiError:
    return ApiError(404, "There is no such script.", "script_not_found", text=said("script_not_found"))


def _one(script: dict[str, Any], busy: dict[str, dict[str, Any]]) -> dict[str, Any]:
    last = user_scripts.last_run(script["id"])
    return {
        **script,
        "next_run": user_scripts.next_run(script),
        "running": busy.get(script["id"]),
        "last_run": {k: v for k, v in last.items() if k != "output"} if last else None,
    }


def _view() -> dict[str, Any]:
    busy = user_scripts.running()
    return {
        "enabled": user_scripts.enabled(),
        "can_limit": user_scripts.limit_available(),
        "max_scripts": user_scripts.MAX_SCRIPTS,
        "max_timeout_min": user_scripts.MAX_TIMEOUT_MIN,
        "scripts": [_one(s, busy) for s in user_scripts.scripts()],
    }


def _note(principal: AuthenticatedPrincipal, request: Request, what: str, **details: Any) -> None:
    from backend.users_db import log_security_event

    log_security_event(
        f"scripts.{what}",
        "success",
        actor_id=getattr(principal, "user_id", None),
        actor_username=principal.username,
        actor_ip=request.client.host if request.client else "",
        details=details,
    )


@router.get("/scripts", dependencies=[ADMIN])
def list_scripts() -> dict[str, Any]:
    """Whether scheduled scripts are on, whether this system can limit one to a folder, and the scripts."""
    return _view()


@router.put("/scripts/enabled", dependencies=[ADMIN])
def switch_scripts(
    req: SwitchIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Turns scheduled scripts on or off. Turning them on asks for confirmation; off never does."""
    if req.enabled and not user_scripts.enabled():
        confirm_or_raise(request, principal, "scripts.enable")
    user_scripts.set_enabled(req.enabled)
    _note(principal, request, "switch", enabled=req.enabled)
    return _view()


@router.post("/scripts", dependencies=[ADMIN, Depends(require_confirmation("scripts.save"))])
def add_script(
    req: ScriptIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Adds a script."""
    try:
        made = user_scripts.save(req.model_dump())
    except user_scripts.ScriptError as e:
        raise _refused(e) from e
    _note(principal, request, "save", script=made["name"], new=True, limited_to=made["limit_folder"])
    return _view()


@router.put("/scripts/{script_id}", dependencies=[ADMIN, Depends(require_confirmation("scripts.save"))])
def change_script(
    script_id: str,
    req: ScriptIn,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Changes a script: its text, its schedule, its folder limit or its time limit."""
    try:
        made = user_scripts.save(req.model_dump(), script_id)
    except user_scripts.ScriptError as e:
        raise _refused(e) from e
    except KeyError:
        raise _missing() from None
    _note(principal, request, "save", script=made["name"], new=False, limited_to=made["limit_folder"])
    return _view()


@router.delete("/scripts/{script_id}", dependencies=[ADMIN])
def remove_script(
    script_id: str, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Takes a script away, with the record of its runs."""
    script = user_scripts.get(script_id)
    if script is None or not user_scripts.delete(script_id):
        raise _missing()
    _note(principal, request, "delete", script=script["name"])
    return _view()


@router.post("/scripts/{script_id}/run", dependencies=[ADMIN])
def run_script(script_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """Starts a script now. Its end is written to the security log like a scheduled run's."""
    try:
        return {"status": "started", **user_scripts.start(script_id, "by_hand", principal.username or "")}
    except KeyError:
        raise _missing() from None
    except user_scripts.NotNow as e:
        raise _refused(e, 409) from e


@router.post("/scripts/{script_id}/stop", dependencies=[ADMIN])
def stop_script(script_id: str) -> dict[str, Any]:
    """Stops a run that is going, with everything the script started."""
    if user_scripts.get(script_id) is None:
        raise _missing()
    return {"stopped": user_scripts.stop(script_id)}


@router.get("/scripts/{script_id}/runs", dependencies=[ADMIN])
def script_runs(script_id: str) -> dict[str, Any]:
    """The last runs of a script, newest first, each with the end of what it printed."""
    if user_scripts.get(script_id) is None:
        raise _missing()
    return {"running": user_scripts.running().get(script_id), "runs": user_scripts.runs(script_id)}
