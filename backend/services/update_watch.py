"""The daily update check's own record (Settings decision 5): whether it runs, when it last ran,
what it found, and which version was already announced, so each new version is announced once.
The check itself lives with the update routes (backend/api/update_watch.py)."""

from __future__ import annotations

import os
from typing import Any

from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, read_json

STATE_FILE = os.path.join(DATA_DIR, "update_watch.json")
EVERY_SECS = 86400


def _defaults() -> dict[str, Any]:
    return {"daily": True, "last_check": 0.0, "available": False, "latest": "", "announced": ""}


def state() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    return {**_defaults(), **(data if isinstance(data, dict) else {})}


def set_daily(on: bool) -> dict[str, Any]:
    st = state()
    st["daily"] = bool(on)
    atomic_write_json(STATE_FILE, st)
    return st


def due(now: float) -> bool:
    st = state()
    return bool(st["daily"]) and now - float(st["last_check"] or 0) >= EVERY_SECS


def record(result: dict[str, Any], now: float) -> str:
    """Keeps what a check found; returns the version to announce now, or "" when it was announced
    already, there is none, or the check failed."""
    st = state()
    st["last_check"] = now
    if result.get("error"):
        atomic_write_json(STATE_FILE, st)
        return ""
    available = bool(result.get("update_available"))
    latest = str(result.get("latest_version") or result.get("latest_tag") or "")
    st["available"] = available
    st["latest"] = latest if available else ""
    announce = latest if available and latest and latest != st["announced"] else ""
    if announce:
        st["announced"] = announce
    atomic_write_json(STATE_FILE, st)
    return announce
