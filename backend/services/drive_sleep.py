"""The "let hard drives sleep" setting (owner decision 23 Nov 2026: build it, off by default).

Kept in drive_sleep.json; the timer itself lives in each drive (hardware/drive_sleep.py) and is set
when the setting changes and each time Kiboto starts. Only where Kiboto is the machine's system:
elsewhere the host has its own spin-down setting and Kiboto leaves it to that."""

from __future__ import annotations

import os
from typing import Any

from backend import runtime
from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, json_locked, read_json
from backend.hardware import drive_sleep

STATE_FILE = os.path.join(DATA_DIR, "drive_sleep.json")


def state() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    data = data if isinstance(data, dict) else {}
    minutes = data.get("minutes", 0)
    return {"minutes": minutes if minutes in drive_sleep.CHOICES else 0, "last": data.get("last") or []}


def public_state() -> dict[str, Any]:
    st = state()
    here = runtime.managed_host()
    return {**st, "choices": list(drive_sleep.CHOICES), "applies": here}


@json_locked(lambda *a, **k: STATE_FILE)
def save(minutes: int) -> dict[str, Any]:
    from backend.errors import SaidError

    if not runtime.managed_host():
        raise SaidError("On this machine its own system decides when drives sleep.", "drive_sleep_not_here")
    if minutes not in drive_sleep.CHOICES:
        raise SaidError("Choose one of the times in the list.", "drive_sleep_choice")
    last = drive_sleep.apply(minutes)
    atomic_write_json(STATE_FILE, {"minutes": minutes, "last": last})
    return public_state()


@json_locked(lambda *a, **k: STATE_FILE)
def at_start() -> list[dict[str, Any]]:
    """Sets the timers again after a restart (a drive forgets its timer when it loses power).
    Nothing while the setting is off: a drive's own timer, if it had one, is left as it was."""
    st = state()
    if not runtime.managed_host() or not st["minutes"]:
        return []
    last = drive_sleep.apply(st["minutes"])
    atomic_write_json(STATE_FILE, {"minutes": st["minutes"], "last": last})
    return last
