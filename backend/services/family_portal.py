"""The family portal (ADR 0007, the owner's decision D12 part 2): a person's own files and photos in
a browser from anywhere, for family members who can't install the Tailscale app.

This module keeps its state: whether it is on, who may use it, the single-use join links that let a
person make a passkey on the portal's address, and the portal's own sessions. A portal session is a
`zpt_` token that only the portal's routes (backend/api/portal.py) accept; the main API refuses it
(backend.auth.get_current_session). Sessions live in memory: a restart signs everyone out of the
portal, which costs one passkey touch.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

STATE_FILE = os.path.join(DATA_DIR, "family_portal.json")
PREFIX = "zpt_"
SESSION_IDLE_SECS = 30 * 60
SESSION_MAX_SECS = 12 * 3600
INVITE_SECS = 7 * 86400
INVITE_TRIES = 10  # a join link stops working after this many attempts
_LOCK = threading.Lock()
_SESSIONS: dict[str, dict[str, Any]] = {}  # sha256 of the token -> {user_id, started, seen}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _state() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def _save(state: dict[str, Any]) -> None:
    atomic_write_json(STATE_FILE, state)


def is_on() -> bool:
    return bool(_state().get("on"))


def people() -> list[str]:
    return [str(p) for p in _state().get("people") or []]


def allowed(user_id: str) -> bool:
    return bool(user_id) and user_id in people()


def status() -> dict[str, Any]:
    state = _state()
    now = time.time()
    invites = {
        v.get("user_id"): v.get("expires", 0)
        for v in (state.get("invites") or {}).values()
        if v.get("expires", 0) > now
    }
    with _LOCK:
        signed_in = sorted({s["user_id"] for s in _SESSIONS.values()})
    return {"on": bool(state.get("on")), "people": people(), "invites": invites, "signed_in": signed_in}


def set_on(on: bool) -> None:
    with _LOCK:
        state = _state()
        state["on"] = bool(on)
        _save(state)
    if not on:
        end_sessions()
    logger.info("[Portal] turned %s", "on" if on else "off")


def allow(user_id: str, yes: bool) -> None:
    """Lets a person use the portal, or stops them (their sessions and join link end at once)."""
    with _LOCK:
        state = _state()
        listed = [p for p in state.get("people") or [] if p != user_id]
        if yes:
            listed.append(user_id)
        state["people"] = listed
        if not yes:
            state["invites"] = {k: v for k, v in (state.get("invites") or {}).items() if v.get("user_id") != user_id}
        _save(state)
    if not yes:
        end_sessions(user_id)


def make_invite(user_id: str) -> str:
    """A single-use join link token for a person allowed on the portal; an earlier one stops working."""
    if not allowed(user_id):
        raise ValueError("Allow this person on the family portal first.")
    token = secrets.token_urlsafe(32)
    with _LOCK:
        state = _state()
        invites = {k: v for k, v in (state.get("invites") or {}).items() if v.get("user_id") != user_id}
        invites[_hash(token)] = {"user_id": user_id, "expires": time.time() + INVITE_SECS, "tries": 0}
        state["invites"] = invites
        _save(state)
    return token


def withdraw_invite(user_id: str) -> None:
    with _LOCK:
        state = _state()
        state["invites"] = {k: v for k, v in (state.get("invites") or {}).items() if v.get("user_id") != user_id}
        _save(state)


def invite_user(token: str) -> dict[str, Any] | None:
    """The person a join link is for, counting the try; None when it is unknown, used, expired,
    tried too often, or the portal is off or no longer lets that person in."""
    if not token or not is_on():
        return None
    key = _hash(token)
    with _LOCK:
        state = _state()
        entry = (state.get("invites") or {}).get(key)
        if not entry:
            return None
        entry["tries"] = int(entry.get("tries", 0)) + 1
        if entry["tries"] > INVITE_TRIES or entry.get("expires", 0) < time.time():
            state["invites"].pop(key, None)
            _save(state)
            return None
        _save(state)
    if not allowed(entry["user_id"]):
        return None
    return active_user(entry["user_id"])


def use_invite(token: str) -> None:
    with _LOCK:
        state = _state()
        (state.get("invites") or {}).pop(_hash(token), None)
        _save(state)


def active_user(user_id: str) -> dict[str, Any] | None:
    from backend.users_db import get_user_by_id

    user = get_user_by_id(user_id) if user_id else None
    return user if user and user.get("status") == "active" else None


def start_session(user_id: str) -> str:
    token = PREFIX + secrets.token_urlsafe(32)
    now = time.time()
    with _LOCK:
        _SESSIONS[_hash(token)] = {"user_id": user_id, "started": now, "seen": now}
    return token


def session_user(token: str) -> dict[str, Any] | None:
    """The person a portal session belongs to while it is valid: the portal on, the person still
    allowed and active, used within SESSION_IDLE_SECS and younger than SESSION_MAX_SECS."""
    if not token or not token.startswith(PREFIX):
        return None
    key = _hash(token)
    now = time.time()
    with _LOCK:
        sess = _SESSIONS.get(key)
        if not sess:
            return None
        if now - sess["seen"] > SESSION_IDLE_SECS or now - sess["started"] > SESSION_MAX_SECS:
            _SESSIONS.pop(key, None)
            return None
    user_id = sess["user_id"]
    user = active_user(user_id) if is_on() and allowed(user_id) else None
    with _LOCK:
        if user is None:
            _SESSIONS.pop(key, None)
            return None
        sess["seen"] = now
    return user


def end_session(token: str) -> None:
    with _LOCK:
        _SESSIONS.pop(_hash(token or ""), None)


def end_sessions(user_id: str = "") -> int:
    with _LOCK:
        gone = [k for k, s in _SESSIONS.items() if not user_id or s["user_id"] == user_id]
        for k in gone:
            _SESSIONS.pop(k, None)
    return len(gone)


def principal_for(user: dict[str, Any]):
    """Who the portal reads files as: the person, with no scopes at all, so the files rules treat
    them as a family account whatever their role (their home and the shares granted to them)."""
    from backend.auth import AuthenticatedPrincipal

    return AuthenticatedPrincipal(user_id=user["id"], username=user["username"], role_id="portal", scopes=[])


# --- publishing through Funnel (step 2): /portal on the share links' port, nothing else ---------

NOT_CONNECTED = "Tailscale isn't connected on this NAS."
NOT_OFF = "Tailscale did not confirm that the family portal is off the internet. Try again."


def _served(handlers: dict[str, Any]) -> bool:
    from backend.services import tailnet_ports

    return any(p.rstrip("/") == tailnet_ports.PORTAL_PATH for p in handlers)


def address(dns: str = "") -> str:
    from backend.services import public_links, tailnet_ports

    dns = dns or public_links.dns_name()
    return f"https://{dns}:{tailnet_ports.SHARE_LINKS}{tailnet_ports.PORTAL_PATH}/" if dns else ""


def live(dns: str = "") -> bool:
    """Whether Funnel puts the portal on the internet right now."""
    from backend.services import public_links

    dns = dns or public_links.dns_name()
    if not dns:
        return False
    handlers, public, _read = public_links.port_state(dns)
    return public and _served(handlers)


def publish(web_port: int, move_immich: bool = False) -> dict[str, Any]:
    """Puts /portal on the internet through Funnel and turns the portal on. {ok, error, approval_url,
    funnel}: until the tailnet's owner allowed Funnel and HTTPS certificates, nothing is published
    and `funnel` says which step is missing."""
    from backend.services import public_links, tailnet_ports

    dns = public_links.dns_name()
    if not dns:
        return {"ok": False, "error": NOT_CONNECTED}
    ready = public_links.funnel_readiness()
    if not ready["ready"]:
        return {"ok": False, "error": "", "funnel": ready}
    handlers, _public, _read = public_links.port_state(dns)
    if move_immich and public_links.immich_to_move(dns):
        moved = public_links.move_immich_off(dns)
        if moved:
            return {"ok": False, "error": moved}
        handlers, _public, _read = public_links.port_state(dns)
    if public_links.others_on_port(handlers):
        return {"ok": False, "error": public_links.OTHERS_ON_PORT}
    target = f"http://127.0.0.1:{int(web_port)}{tailnet_ports.PORTAL_PATH}"
    code, out = public_links.tailscale(
        [
            "funnel",
            "--bg",
            "--yes",
            f"--https={tailnet_ports.SHARE_LINKS}",
            f"--set-path={tailnet_ports.PORTAL_PATH}",
            target,
        ]
    )
    approval = public_links.APPROVAL.search(out or "") if out else None
    if code != 0 and not approval:
        return {"ok": False, "error": (out or "Tailscale did not publish the portal.").strip()[:300]}
    set_on(True)
    logger.info("[Portal] published at %s", address(dns))
    return {"ok": True, "error": "", "approval_url": approval.group(0) if approval else ""}


def unpublish() -> dict[str, Any]:
    """Takes /portal off the internet and turns the portal off; "off" only once Tailscale shows it."""
    from backend.services import public_links, tailnet_ports

    set_on(False)
    dns = public_links.dns_name()
    if not dns:
        return {"ok": True, "error": ""}
    public_links.tailscale(
        ["funnel", f"--https={tailnet_ports.SHARE_LINKS}", f"--set-path={tailnet_ports.PORTAL_PATH}", "off"]
    )
    handlers, public, read = public_links.port_state(dns)
    if not read or (public and _served(handlers)):
        logger.warning("[Portal] taking it off the internet was not confirmed by Tailscale")
        return {"ok": False, "error": NOT_OFF}
    return {"ok": True, "error": ""}


def owner_view() -> dict[str, Any]:
    """The owner's card: on, live, the address, Funnel's steps, and each person with what they have."""
    from backend.services import passkeys, public_links
    from backend.users_db import list_users

    dns = public_links.dns_name()
    st = status()
    rows = []
    for u in list_users():
        if u.get("status") != "active":
            continue
        rows.append(
            {
                "id": u["id"],
                "username": u["username"],
                "name": u.get("display_name") or u["username"],
                "allowed": u["id"] in st["people"],
                "passkey": any(p["portal_only"] for p in passkeys.list_for(u["id"])),
                "invite_until": st["invites"].get(u["id"], 0),
                "signed_in": u["id"] in st["signed_in"],
            }
        )
    return {
        "on": st["on"],
        "live": live(dns),
        "address": address(dns),
        "tailscale": bool(dns),
        "funnel": public_links.funnel_readiness(),
        "immich_moves_to": public_links.immich_to_move(dns) if dns else "",
        "people": rows,
    }
