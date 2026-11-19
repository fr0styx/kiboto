"""Coloured labels on files and folders in the File Explorer (re-audit 19 Nov 2026, R11).

Each person has six colours, can give each a name ("Taxes", "To sort") and put one on any file
or folder they may open. Labels are that person's own: they are kept with the account, not in
the files, so nothing on disk changes and other people do not see them. A label follows a path:
renaming a file or folder in the File Explorer takes its label (and those inside a folder) along;
a file moved elsewhere loses it.
"""

import os
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import backend.config as config
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.fsutil import atomic_write_json, json_locked, read_json, resolve_within
from backend.services import fs_transfer
from backend.services.path_access import ALLOWED_BROWSE_ROOTS, check_user_path_access

router = APIRouter()

COLOURS = ("red", "orange", "yellow", "green", "blue", "purple")
MAX_ITEMS = 2000
_LOCK = threading.Lock()
SCOPE = Depends(require_scope("shares:read", "storage:read", "system:view"))


def _file() -> str:
    return os.path.join(config.DATA_DIR, "fm_labels.json")


def _key(principal: AuthenticatedPrincipal | None) -> str:
    return ((principal.username if principal else "") or "_shared").lower()


def _load(principal: AuthenticatedPrincipal | None) -> dict[str, Any]:
    data = read_json(_file(), {})
    mine = data.get(_key(principal), {}) if isinstance(data, dict) else {}
    mine = mine if isinstance(mine, dict) else {}
    raw_items, raw_names = mine.get("items"), mine.get("names")
    items: dict[Any, Any] = raw_items if isinstance(raw_items, dict) else {}
    names: dict[Any, Any] = raw_names if isinstance(raw_names, dict) else {}
    return {
        "items": {p: c for p, c in items.items() if isinstance(p, str) and c in COLOURS},
        "names": {c: str(n)[:40] for c, n in names.items() if c in COLOURS and n},
    }


@json_locked(lambda *a, **k: _file())
def _save(principal: AuthenticatedPrincipal | None, mine: dict[str, Any]) -> None:
    data = read_json(_file(), {})
    if not isinstance(data, dict):
        data = {}
    data[_key(principal)] = mine
    atomic_write_json(_file(), data)


def _view(mine: dict[str, Any]) -> dict[str, Any]:
    return {"colours": list(COLOURS), "names": mine["names"], "items": mine["items"]}


class LabelIn(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)
    colour: str | None = Field(default=None, max_length=12)


class LabelNameIn(BaseModel):
    colour: str = Field(..., max_length=12)
    name: str = Field(default="", max_length=40)


@router.get("/fs/labels", dependencies=[SCOPE])
def fs_list_labels(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """The signed-in person's labels: the colours, the names they gave them, and path -> colour."""
    return _view(_load(principal))


@router.put("/fs/labels", dependencies=[SCOPE])
def fs_set_label(req: LabelIn, principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """Puts a colour on a file or folder; no colour takes the label off."""
    path = req.path.rstrip("/") or "/"
    if req.colour is not None and req.colour not in COLOURS:
        raise HTTPException(status_code=400, detail="Unknown label colour.")
    with _LOCK:
        mine = _load(principal)
        if req.colour is None:
            mine["items"].pop(path, None)
        else:
            check_user_path_access(path, principal)
            real = resolve_within(path, ALLOWED_BROWSE_ROOTS)
            if real is None or not os.path.lexists(real):
                raise HTTPException(status_code=400, detail="That file or folder can't be labelled.")
            if path not in mine["items"] and len(mine["items"]) >= MAX_ITEMS:
                raise HTTPException(status_code=400, detail=f"You can label up to {MAX_ITEMS} files and folders.")
            mine["items"][path] = req.colour
        _save(principal, mine)
    return _view(mine)


@router.put("/fs/labels/names", dependencies=[SCOPE])
def fs_name_label(
    req: LabelNameIn, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Gives a colour a name of the person's own; an empty name goes back to the colour's own word."""
    if req.colour not in COLOURS:
        raise HTTPException(status_code=400, detail="Unknown label colour.")
    name = req.name.strip()
    with _LOCK:
        mine = _load(principal)
        if name:
            mine["names"][req.colour] = name
        else:
            mine["names"].pop(req.colour, None)
        _save(principal, mine)
    return _view(mine)


@json_locked(lambda *a, **k: _file())
def _move_labels(key: str, old: str, new: str) -> int:
    data = read_json(_file(), {})
    mine = data.get(key) if isinstance(data, dict) else None
    items = mine.get("items") if isinstance(mine, dict) else None
    if not isinstance(items, dict):
        return 0
    hits = [p for p in items if p == old or p.startswith(old + "/")]
    for p in hits:
        items[new + p[len(old) :]] = items.pop(p)
    if hits:
        atomic_write_json(_file(), data)
    return len(hits)


def moved(old: str, new: str, username: str | None) -> int:
    """A file or folder was renamed or moved: its label, and the labels of what is inside it, follow.
    Returns how many labels moved. Never raises: a label must not fail a rename."""
    old, new = old.rstrip("/"), new.rstrip("/")
    if not old or not new or old == new:
        return 0
    try:
        with _LOCK:
            return _move_labels((username or "_shared").lower(), old, new)
    except OSError:
        return 0


# a move made in the background (Files → Move to, cut and paste, drag) carries the label along
if moved not in fs_transfer.MOVED_HOOKS:
    fs_transfer.MOVED_HOOKS.append(moved)
