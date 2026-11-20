"""Which shared folders are merged ones (data tiering on Kiboto's own pools), for the parts of
Kiboto that only need to know it: snapshots take a merged folder's own files from the hidden
folder beside it, and a pool that holds one side is not taken away. Making and mounting them is
backend/services/tier_merge.py."""

import os
from typing import Any

from backend.config import DATA_DIR
from backend.fsutil import read_json

STATE_FILE = os.path.join(DATA_DIR, "tier_merge.json")


def merges() -> list[dict[str, Any]]:
    data = read_json(STATE_FILE, {})
    kept = data.get("merges") if isinstance(data, dict) else None
    return [m for m in kept or [] if isinstance(m, dict) and m.get("path") and m.get("fast") and m.get("slow")]


def of(path: str) -> dict[str, Any] | None:
    """The merge at this shared folder's path, if it is a merged one."""
    path = path.rstrip("/")
    return next((m for m in merges() if m["path"] == path), None)


def held_on(mountpoint: str) -> list[str]:
    """The merged folders that have a side on the pool mounted here: it must not be taken away."""
    at = mountpoint.rstrip("/")
    if not at:
        return []
    return sorted({m["name"] for m in merges() if any(p.startswith(at + "/") for p in (m["fast"], m["slow"]))})
