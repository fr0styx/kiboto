"""Checks that ask a service outside the home, each off until an administrator turns it on
(the owner's decision, 19 Nov 2026). Kiboto calls nothing outside for these by default; the
Security page has one switch per check and says what each one sends (docs/PRIVACY.md too)."""

from __future__ import annotations

import os

from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, read_json

STATE_FILE = os.path.join(DATA_DIR, "outside_checks.json")
# the checks this version has, in the order the page shows them
CHECKS = ("leaked_passwords", "internet_speed", "weakness_feed")


def state() -> dict[str, bool]:
    data = read_json(STATE_FILE, {})
    data = data if isinstance(data, dict) else {}
    return {name: bool(data.get(name, False)) for name in CHECKS}


def enabled(name: str) -> bool:
    return state().get(name, False)


def set_enabled(name: str, on: bool) -> dict[str, bool]:
    if name not in CHECKS:
        raise KeyError(name)
    st = state()
    st[name] = bool(on)
    atomic_write_json(STATE_FILE, st)
    return st
