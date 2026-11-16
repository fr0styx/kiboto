"""Kib's favourites, one list per person (AI 3).

They were one list in Kib's settings: every person's star showed for everyone, and one person's
star changed what all the others saw. Now each account keeps its own, in a file of its own beside
the File Explorer's favourites; the settings file no longer holds them.
"""

import os
from typing import Any

from backend import config
from backend.fsutil import atomic_write_json, json_locked, read_json

MAX = 200


def _file() -> str:
    return os.path.join(config.DATA_DIR, "kib_favorites.json")


def _key(principal: Any) -> str:
    return str(getattr(principal, "username", "") or "").lower()


def load(principal: Any) -> list[str]:
    """This person's favourites; nobody known has none."""
    key = _key(principal)
    if not key:
        return []
    data = read_json(_file(), {})
    items = data.get(key, []) if isinstance(data, dict) else []
    return [p for p in items if isinstance(p, str)]


@json_locked(lambda *a, **k: _file())
def toggle(principal: Any, path: str) -> tuple[bool, list[str]]:
    """Adds or removes one path for this person; returns whether it is a favourite now, and the list."""
    key = _key(principal)
    if not key:
        raise ValueError("Favourites belong to a person; sign in first.")
    data = read_json(_file(), {})
    if not isinstance(data, dict):
        data = {}
    items = [p for p in data.get(key, []) if isinstance(p, str)]
    if path in items:
        items.remove(path)
        now = False
    else:
        items = [path, *items][:MAX]
        now = True
    data[key] = items
    atomic_write_json(_file(), data)
    return now, items


@json_locked(lambda *a, **k: _file())
def adopt_shared(principal: Any, shared: list[str]) -> None:
    """The old shared list goes to the first administrator who opens Kib after the update, once."""
    key = _key(principal)
    if not key or not shared:
        return
    data = read_json(_file(), {})
    if not isinstance(data, dict):
        data = {}
    mine = [p for p in data.get(key, []) if isinstance(p, str)]
    data[key] = (mine + [p for p in shared if isinstance(p, str) and p not in mine])[:MAX]
    atomic_write_json(_file(), data)
