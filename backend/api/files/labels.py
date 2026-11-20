"""Coloured labels on files and folders in the File Explorer (re-audit 19 Nov 2026, R11).

Each person has six colours, can give each a name ("Taxes", "To sort") and put one on any file
or folder they may open. Labels are that person's own: they are kept with the account, not in
the files, so nothing on disk changes and other people do not see them. A label follows a path:
renaming a file or folder in the File Explorer takes its label (and those inside a folder) along;
a file moved elsewhere loses it.
"""

import os
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import backend.config as config
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.fsutil import atomic_write_json, json_locked, read_json, resolve_within
from backend.services import fs_transfer, recycle_bin
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
    was = data.get(_key(principal))
    # only the labels and their names are replaced: what waits in the Recycle Bin stays on record
    data[_key(principal)] = {**(was if isinstance(was, dict) else {}), **mine}
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


def gone_from(principal: AuthenticatedPrincipal | None, folder: str, names: set[str]) -> int:
    """A folder was just listed: labels on things that are no longer in it are dropped, with those
    inside a folder that is gone. A file deleted over SMB or by an app never passes the File
    Explorer, so its label stayed for good. Only the listing is used: no disk is asked anything
    more. An empty listing changes nothing: a pool that is not mounted looks like that."""
    if principal is None or not names or not os.path.exists(_file()):
        return 0
    base = folder.rstrip("/") + "/"
    with _LOCK:
        mine = _load(principal)
        gone = [p for p in mine["items"] if p.startswith(base) and p[len(base) :].split("/")[0] not in names]
        for p in gone:
            del mine["items"][p]
        if gone:
            _save(principal, mine)
    return len(gone)


# --- deleted files -----------------------------------------------------------------------------
# A label goes into the Recycle Bin with its file and comes back with it. It is kept a little
# longer than the bin keeps anything, then forgotten.
BINNED_KEEP_SECS = (recycle_bin.KEEP_DAYS + 2) * 86400


def _people(data: Any) -> list[dict[str, Any]]:
    """Each person's record that has labels, with a place for the ones in the bin."""
    out = []
    for mine in data.values() if isinstance(data, dict) else []:
        if isinstance(mine, dict) and isinstance(mine.get("items"), dict):
            if not isinstance(mine.get("binned"), dict):
                mine["binned"] = {}
            out.append(mine)
    return out


def _waiting(entry: Any) -> bool:
    """A well-formed record of a label in the bin: [colour, when it went there]."""
    return (
        isinstance(entry, list)
        and len(entry) == 2
        and isinstance(entry[1], (int, float))
        and not isinstance(entry[1], bool)
    )


@json_locked(lambda *a, **k: _file())
def _to_bin(path: str, kept_as: str, now: float) -> int:
    data = read_json(_file(), {})
    hits = dropped = 0
    for mine in _people(data):
        items, binned = mine["items"], mine["binned"]
        for p in [p for p in items if p == path or p.startswith(path + "/")]:
            binned[kept_as + p[len(path) :]] = [items.pop(p), now]
            hits += 1
        for p in [p for p, v in binned.items() if not _waiting(v)]:
            del binned[p]
            dropped += 1
        for p in [p for p, v in binned.items() if now - float(v[1]) >= BINNED_KEEP_SECS]:
            del binned[p]  # the bin emptied itself long ago
            dropped += 1
    if hits or dropped:
        atomic_write_json(_file(), data)
    return hits


@json_locked(lambda *a, **k: _file())
def _from_bin(was: str, now_at: str) -> int:
    data = read_json(_file(), {})
    hits = 0
    for mine in _people(data):
        items, binned = mine["items"], mine["binned"]
        for p in [p for p in binned if p == was or p.startswith(was + "/")]:
            entry = binned.pop(p)
            colour = entry[0] if isinstance(entry, list) and entry else None
            if colour in COLOURS:
                items.setdefault(now_at + p[len(was) :], colour)  # a label put there meanwhile stays
                hits += 1
    if hits:
        atomic_write_json(_file(), data)
    return hits


def deleted(path: str, kept_as: str | None = None, now: float | None = None) -> int:
    """A file or folder went to the Recycle Bin: its labels (everyone's, and those of what is inside)
    leave the lists and wait. `kept_as` is the path the bin will restore it to. Never raises."""
    path, kept_as = path.rstrip("/"), (kept_as or path).rstrip("/")
    if not path or not kept_as:
        return 0
    try:
        with _LOCK:
            return _to_bin(path, kept_as, time.time() if now is None else now)
    except (OSError, ValueError, TypeError):
        return 0


def restored(was: str, now_at: str) -> int:
    """It came back from the bin, to where it was or somewhere else: its labels come back with it."""
    was, now_at = was.rstrip("/"), now_at.rstrip("/")
    if not was or not now_at:
        return 0
    try:
        with _LOCK:
            return _from_bin(was, now_at)
    except (OSError, ValueError, TypeError):
        return 0


# a move made in the background (Files → Move to, cut and paste, drag) carries the label along
if moved not in fs_transfer.MOVED_HOOKS:
    fs_transfer.MOVED_HOOKS.append(moved)
