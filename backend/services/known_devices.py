"""Sign-ins from a device an account has not used before (re-audit 19 Nov 2026, R1).

A stolen password shows up as a sign-in from somewhere new. Kiboto remembers, per person, the
kinds of device they have signed in from (browser and system, e.g. "Chrome on Windows"; never a
fingerprint). The first sign-in from another kind is written to the security log, sent to the
administrators through the security alerts, and pushed to the person's own devices.

The very first device of an account is not "new", and on an install that predates this feature
the devices that are signed in right now are taken as known, so an update alerts nobody.
"""

import ipaddress
import logging
import sqlite3
import threading
import time
from typing import Any

from backend.ignored_errors import ignored

logger = logging.getLogger("Kiboto")

# checked in this order: Edge, Opera and Samsung's browser also say "Chrome", Chrome also says "Safari"
_BROWSERS = (
    ("Edg", "Edge"),
    ("OPR/", "Opera"),
    ("SamsungBrowser/", "Samsung Internet"),
    ("FxiOS/", "Firefox"),
    ("Firefox/", "Firefox"),
    ("CriOS/", "Chrome"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
)
_SYSTEMS = (
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Android", "Android"),
    ("Windows", "Windows"),
    ("Macintosh", "Mac"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
)


def device_parts(user_agent: str) -> tuple[str, str]:
    """(browser, system) read from a User-Agent; a program that is no browser gives (its name, "")."""
    ua = str(user_agent or "")
    system = next((name for mark, name in _SYSTEMS if mark in ua), "")
    browser = next((name for mark, name in _BROWSERS if mark in ua), "")
    if not browser:
        browser = ua.split("/")[0].split(" ")[0][:40]  # "curl/8.5.0" -> "curl"
        system = system if browser.lower().startswith("mozilla") else ""
        browser = "" if browser.lower().startswith("mozilla") else browser
    return browser, system


def describe(user_agent: str) -> str:
    """ "Chrome on Windows", "Safari on iPhone", "curl"; "" when the device says nothing about itself."""
    browser, system = device_parts(user_agent)
    if browser and system:
        return f"{browser} on {system}"
    return browser or system


def _key(user_agent: str) -> str:
    browser, system = device_parts(user_agent)
    return f"{browser}|{system}".lower()


def outside_home(ip: str) -> bool:
    """Whether the address is on the internet (not the home network, a VPN or this machine)."""
    try:
        return ipaddress.ip_address(str(ip or "").split("%")[0]).is_global
    except ValueError:
        return False


def note_signin(
    user_id: str, ip: str = "", user_agent: str = "", now: float | None = None, db_path: str | None = None
) -> dict[str, Any] | None:
    """Remembers this sign-in's device. Returns {"device", "outside"} when the account has used
    other devices but never this kind; None for a known device or the account's first one."""
    from backend.users_db import users_db_session

    now = time.time() if now is None else now
    key = _key(user_agent)
    with users_db_session(db_path) as conn:
        known = {r[0] for r in conn.execute("SELECT device_key FROM known_devices WHERE user_id = ?", (user_id,))}
        if not known:
            # first sign-in since the feature exists: whatever is signed in now is known too
            agents = [
                r[0] for r in conn.execute("SELECT DISTINCT user_agent FROM sessions WHERE user_id = ?", (user_id,))
            ]
            for ua in {*agents, user_agent}:
                conn.execute(
                    "INSERT OR IGNORE INTO known_devices (user_id, device_key, label, first_seen, last_seen, first_ip) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, _key(ua), describe(ua), now, now, ip if ua == user_agent else ""),
                )
            return None
        if key in known:
            conn.execute(
                "UPDATE known_devices SET last_seen = ? WHERE user_id = ? AND device_key = ?", (now, user_id, key)
            )
            return None
        conn.execute(
            "INSERT INTO known_devices (user_id, device_key, label, first_seen, last_seen, first_ip) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, key, describe(user_agent), now, now, ip),
        )
    return {"device": describe(user_agent) or "?", "outside": outside_home(ip)}


def tell_person(username: str, device: str, ip: str) -> None:
    """A push to the person's own devices, in the household's language; never blocks the sign-in."""

    def _send() -> None:
        try:
            from backend import i18n
            from backend.services import web_push
            from backend.services.notifications import alert_language

            lang = alert_language()
            params = {"device": device, "ip": ip or "?"}
            web_push.notify(
                i18n.text("alert.new_device.title", "New sign-in to your account", params, lang),
                i18n.text(
                    "alert.new_device.msg",
                    "{device}, from {ip}. If this wasn't you, change your password and sign out the other devices.",
                    params,
                    lang,
                ),
                level="warning",
                users=[username],
            )
        except (sqlite3.Error, OSError, RuntimeError, ValueError):
            ignored("backend.services.known_devices.tell_person")

    threading.Thread(target=_send, name="new-device-push", daemon=True).start()


def signed_in(user: dict[str, Any], ip: str, user_agent: str, method: str) -> bool:
    """Called for every successful sign-in. True when it came from a new kind of device."""
    try:
        new = note_signin(str(user["id"]), ip, user_agent)
    except (sqlite3.Error, OSError):  # a locked or unreadable database must not stop a sign-in
        ignored("backend.services.known_devices.signed_in")
        return False
    if not new:
        return False
    from backend.users_db import log_security_event

    log_security_event(
        "auth.login.new_device",
        "success",
        actor_id=user["id"],
        actor_username=user["username"],
        actor_ip=ip,
        actor_user_agent=user_agent,
        details={"device": new["device"], "outside": new["outside"], "method": method},
    )
    tell_person(str(user["username"]), new["device"], ip)
    return True
