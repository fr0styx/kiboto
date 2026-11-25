"""The family portal's routes (ADR 0007): everything under /portal, the only path Funnel publishes
for it. Its sessions are its own (backend/services/family_portal.py) and reach nothing else; files
are read with no scopes, so a person sees their home and the shares granted to them, whatever
their role. Sign-in is by passkey only. Step 1 reads; nothing here writes a file.
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend import rate_limit
from backend.services import family_portal, passkeys

router = APIRouter(prefix="/portal", include_in_schema=False)
COOKIE = "kiboto_portal"
FAIL_LIMIT, FAIL_WINDOW = 10, 900  # failed sign-ins per address


class Signed(BaseModel):
    ticket: str
    credential: dict[str, Any]


class Join(BaseModel):
    token: str


class JoinFinish(Join):
    ticket: str
    credential: dict[str, Any]


def _ip(request: Request) -> str:
    from backend.auth import client_ip

    return client_ip(request)


def _on() -> None:
    if not family_portal.is_on():
        raise HTTPException(status_code=404, detail="Not found.")


def _same_site(request: Request) -> None:
    from backend.auth import same_origin

    if not same_origin(request):
        raise HTTPException(status_code=403, detail="Cross-site request blocked.")


def _not_locked(request: Request) -> None:
    wait = rate_limit.waiting(f"portal-fail:{_ip(request)}", FAIL_LIMIT, FAIL_WINDOW)
    if wait:
        raise HTTPException(status_code=429, detail=f"Too many tries. Try again in {wait} seconds.")


def _failed(request: Request, detail: str) -> HTTPException:
    rate_limit.hit(f"portal-fail:{_ip(request)}", FAIL_LIMIT, FAIL_WINDOW)
    return HTTPException(status_code=401, detail=detail)


def _signed_in(request: Request, user: dict[str, Any]) -> JSONResponse:
    from backend.auth import request_is_https

    token = family_portal.start_session(user["id"])
    resp = JSONResponse({"ok": True, "name": user.get("display_name") or user["username"]})
    resp.set_cookie(
        COOKIE,
        token,
        max_age=family_portal.SESSION_MAX_SECS,
        httponly=True,
        secure=request_is_https(request),
        samesite="strict",
        path="/portal",
    )
    return resp


def _who(request: Request) -> tuple[dict[str, Any], Any]:
    _on()
    user = family_portal.session_user(request.cookies.get(COOKIE, ""))
    if not user:
        raise HTTPException(status_code=401, detail="Sign in with your passkey.")
    return user, family_portal.principal_for(user)


@router.get("/api/state")
def state(request: Request) -> dict[str, Any]:
    user = family_portal.session_user(request.cookies.get(COOKIE, "")) if family_portal.is_on() else None
    return {
        "on": family_portal.is_on(),
        "signed_in": bool(user),
        "name": (user.get("display_name") or user["username"]) if user else "",
    }


@router.post("/api/signin/options")
def signin_options(request: Request) -> dict[str, Any]:
    _on()
    _same_site(request)
    _not_locked(request)
    try:
        return passkeys.login_options(request.headers.get("host", ""))
    except passkeys.PasskeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/api/signin/finish")
def signin_finish(req: Signed, request: Request) -> JSONResponse:
    _on()
    _same_site(request)
    _not_locked(request)
    try:
        user_id, _extra = passkeys.login_finish(req.ticket, req.credential, portal=True)
    except passkeys.PasskeyError as e:
        raise _failed(request, str(e)) from e
    user = family_portal.active_user(user_id) if family_portal.allowed(user_id) else None
    if not user:
        raise _failed(request, "This passkey's account can't use the family portal.")
    return _signed_in(request, user)


@router.post("/api/join/options")
def join_options(req: Join, request: Request) -> dict[str, Any]:
    _on()
    _same_site(request)
    _not_locked(request)
    user = family_portal.invite_user(req.token)
    if not user:
        raise _failed(request, "This join link doesn't work any more. Ask for a new one.")
    try:
        out = passkeys.register_options(user, request.headers.get("host", ""))
    except passkeys.PasskeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {**out, "name": user.get("display_name") or user["username"]}


@router.post("/api/join/finish")
def join_finish(req: JoinFinish, request: Request) -> JSONResponse:
    _on()
    _same_site(request)
    _not_locked(request)
    user = family_portal.invite_user(req.token)
    if not user:
        raise _failed(request, "This join link doesn't work any more. Ask for a new one.")
    try:
        passkeys.register_finish(user, req.ticket, req.credential, "Family portal", portal_only=True)
    except passkeys.PasskeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    family_portal.use_invite(req.token)
    return _signed_in(request, user)


@router.post("/api/signout")
def signout(request: Request) -> JSONResponse:
    _same_site(request)
    family_portal.end_session(request.cookies.get(COOKIE, ""))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/portal")
    return resp


@router.get("/api/list")
async def list_folder(request: Request, path: str = "") -> Any:
    _user, principal = _who(request)
    from backend.api.files.browse import browse_folder, folder_asleep
    from backend.services.path_access import check_user_path_access

    await asyncio.to_thread(check_user_path_access, path, principal, allow_list=True)
    if path and await asyncio.to_thread(folder_asleep, path):
        raise HTTPException(status_code=409, detail="This folder is on a drive that is asleep.")
    return await asyncio.to_thread(browse_folder, path, False, principal)


@router.get("/api/picture")
async def picture(request: Request, path: str, thumb: int | None = None, v: str | None = None) -> Any:
    _user, principal = _who(request)
    from backend.api.files.preview import fs_preview_image

    return await fs_preview_image(path, request, thumb=thumb, max_dim=None if thumb else 2560, v=v, principal=principal)


def _readable_file(path: str, principal: Any) -> str:
    from backend.api.files.common import contained
    from backend.services.path_access import check_user_path_access

    check_user_path_access(path, principal)
    target = contained(path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="A folder can't be downloaded here.")
    return target


@router.get("/api/file")
async def download(request: Request, path: str) -> Any:
    _user, principal = _who(request)
    from backend.api.files.common import user_file_headers

    target = await asyncio.to_thread(_readable_file, path, principal)
    media = mimetypes.guess_type(target)[0] or "application/octet-stream"
    return FileResponse(target, media_type=media, filename=os.path.basename(target), headers=user_file_headers(media))
