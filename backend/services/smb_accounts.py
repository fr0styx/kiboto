"""Each person's own system account on Kiboto's own file server, by a number that never changes.

Private folders belong to their person: the file server signs each person in as their own account,
and the folder on disk shows who it is. The numbers start at 20000, far from the system's own and
from the first users a Linux install makes, and a number once given is never given again, so a new
person never inherits an old one's files. Shared folders are not affected: they are written as the
file server's user (nobody:users). Not used on Unraid, where Unraid serves the files.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import backend.config as config
from backend.fsutil import atomic_write_json, read_json

FIRST_UID = 20000
GROUP_ID = 100  # "users": the people may also read and write what the file server writes in shared folders
_LOCK = threading.Lock()


def _file() -> str:
    return os.path.join(config.DATA_DIR, "smb_accounts.json")


def _load() -> dict[str, Any]:
    raw = read_json(_file(), {})
    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
    got = data.get("uids")
    uids: dict[Any, Any] = got if isinstance(got, dict) else {}
    clean = {str(k): v for k, v in uids.items() if isinstance(v, int) and not isinstance(v, bool)}
    top = max(clean.values(), default=FIRST_UID - 1)
    given = data.get("next")
    nxt = given if isinstance(given, int) and not isinstance(given, bool) else FIRST_UID
    return {"uids": clean, "next": max(nxt, top + 1, FIRST_UID)}


def uid_of(username: str) -> int:
    """The person's account number, given now if they had none."""
    name = (username or "").strip().lower()
    if not name:
        raise ValueError("no username")
    with _LOCK:
        data = _load()
        if name not in data["uids"]:
            data["uids"][name] = data["next"]
            data["next"] += 1
            atomic_write_json(_file(), data)
        return data["uids"][name]


def numbers(names: set[str] | list[str]) -> dict[str, int]:
    """The number of each of these people, given to those who had none yet."""
    return {name: uid_of(name) for name in sorted({str(n).lower() for n in names if str(n).strip()})}
