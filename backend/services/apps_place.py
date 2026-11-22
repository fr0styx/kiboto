"""Where the apps of a machine set up for Kiboto keep their data.

Not on the system disk: when that disk fails, apps whose data was on it are gone with it, while
the settings come back from the copy on the pools (pool_copy.py). So the apps' folder is `appdata`
on the first pool Kiboto made or took in, written down the first time it is needed, so it never
moves when more pools come or the first one is renamed in the list. Until there is a pool at all,
apps fall back to the main storage folder on the system disk, and the next time after a pool
exists the folder is chosen again.

A pool that is away does not make apps fall back: its empty mount folder cannot be written to
(pool_registry.protect), so an app fails to start instead of filling the system disk."""

import os

from backend import config
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

FOLDER = "appdata"


def _file() -> str:
    return os.path.join(DATA_DIR, "storage", "apps_place.json")


def recorded() -> str:
    data = read_json(_file(), {}) if os.path.exists(_file()) else {}
    root = data.get("root") if isinstance(data, dict) else ""
    return root if isinstance(root, str) and root.startswith("/") else ""


def _first_pool() -> str:
    from backend.hardware.pal import pool_registry

    for row in pool_registry.load():  # oldest first
        mp = row.get("mountpoint") or ""
        if not row.get("ejected") and mp and os.path.ismount(mp):
            return mp
    return ""


def root() -> tuple[str, bool]:
    """(the apps' folder, whether it is settled on a pool)."""
    known = recorded()
    if known:
        return known, True
    pool = _first_pool()
    if not pool:
        return os.path.join(config.POOL_PATH, FOLDER), False
    chosen = os.path.join(pool, FOLDER)
    os.makedirs(os.path.dirname(_file()), exist_ok=True)
    atomic_write_json(_file(), {"root": chosen})
    logger.info("[Apps] Apps keep their data in %s from now on", chosen)
    return chosen, True
