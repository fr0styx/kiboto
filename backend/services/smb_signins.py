"""Failed SMB sign-ins count against the address, as the web, WebDAV and SFTP ones do.

On a machine set up for Kiboto, its file server writes each failed sign-in as a JSON line
(samba_host.global_lines: auth_json_audit at level 2, failures only). Every EVERY_SECS the new
lines are read: each failure goes to the block-list (ip_block: 20 in 15 minutes block the address
for an hour), and the round's failures go to the sign-in history, one entry per address and
account with how many. Kiboto starts reading at the end of the file, so failures from before a
restart are not counted twice.

Elsewhere the host's or the container's own Samba writes no such log and nothing is read."""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from typing import Any

from backend.config import logger
from backend.services.samba_host import AUTH_LOG

EVERY_SECS = 10
_at: dict[str, Any] = {"ino": None, "off": None}  # where reading stopped; off None: not started


def ip_of(remote: str) -> str:
    """1.2.3.4 from "ipv4:1.2.3.4:51234", 2001:db8::1 from "ipv6:2001:db8::1:51234" or "ipv6:[...]:p"."""
    kind, _, rest = str(remote or "").partition(":")
    if kind not in ("ipv4", "ipv6") or not rest:
        return ""
    if rest.startswith("["):
        return rest[1:].split("]", 1)[0]
    return rest.rsplit(":", 1)[0]


def _failure(line: str) -> dict[str, str] | None:
    try:
        auth = json.loads(line).get("Authentication") or {}
    except (ValueError, AttributeError):
        return None
    status = str(auth.get("status") or "")
    if not status or status == "NT_STATUS_OK":
        return None
    ip = ip_of(auth.get("remoteAddress") or "")
    if not ip:
        return None
    return {"ip": ip, "user": str(auth.get("clientAccount") or "")[:64], "status": status[:64]}


def new_failures(path: str = AUTH_LOG) -> list[dict[str, str]]:
    """The failures written since the last call. The first call only notes where the file ends; a
    file that was replaced or became shorter (the server started a new one) is read from its start."""
    try:
        st = os.stat(path)
    except OSError:
        _at.update(ino=None, off=0)
        return []
    if _at["off"] is None:
        _at.update(ino=st.st_ino, off=st.st_size)
        return []
    if st.st_ino != _at["ino"] or st.st_size < _at["off"]:
        _at.update(ino=st.st_ino, off=0)
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        f.seek(_at["off"])
        chunk = f.read(4 * 1024 * 1024)
        done = chunk.rfind("\n") + 1  # a line still being written is read next time
        for line in chunk[:done].splitlines():
            found = _failure(line)
            if found:
                out.append(found)
        _at["off"] += len(chunk[:done].encode("utf-8", errors="replace"))
    return out


def check_once(path: str = AUTH_LOG) -> int:
    """Counts the new failures; returns how many there were."""
    from backend.services import ip_block
    from backend.users_db import log_security_event

    failures = new_failures(path)
    for f in failures:
        if ip_block.record_auth_failure(f["ip"], "SMB"):
            log_security_event("auth.lockout", "failure", actor_ip=f["ip"], details={"service": "SMB"})
    for (ip, user), count in Counter((f["ip"], f["user"]) for f in failures).items():
        log_security_event(
            "smb.login.failure", "failure", actor_username=user or None, actor_ip=ip, details={"count": count}
        )
    return len(failures)


def keep_watching(rounds: int | None = None) -> None:
    """Background loop on a managed host. `rounds` ends it (tests)."""
    while rounds is None or rounds > 0:
        try:
            check_once()
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning("[Samba] Failed sign-ins could not be read: %s", e)
        time.sleep(EVERY_SECS)
        rounds = None if rounds is None else rounds - 1


def _reset_for_tests() -> None:
    _at.update(ino=None, off=None)
