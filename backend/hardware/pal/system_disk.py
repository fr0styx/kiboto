"""The system disk of a machine set up for Kiboto holds no shared folders.

When that disk fails, what is on it is gone. The settings come back from the copy on the pools
(pool_copy.py) and the apps keep their data on the first pool (apps_place.py); shared folders are
made only on pools, so nothing people put in them lives on the system disk. Until there is a pool
there is nowhere to make one, and Setup and Storage ask for a pool first. A folder shared on the
system disk before this stays shared and says where it is.

Only on a managed host: elsewhere the host decides what its disks are for."""

import os
import shutil
from typing import Any

from backend import runtime

DEFAULT_SHARE = "storage"
# refusals as (sentence, key) for SaidError, raised by the callers (errors.py sits in an import cycle)
ON_SYSTEM_DISK = (
    "Kiboto keeps no shared folders on the system disk. Choose a folder on one of the pools.",
    "share_system_disk",
)
NO_POOL = ("Make a storage pool first. Kiboto keeps no shared folders on the system disk.", "share_no_pool")


def applies() -> bool:
    return runtime.managed_host()


def _pool_rows() -> list[dict[str, Any]]:
    from backend.hardware.pal import pool_registry

    return pool_registry.load()


def first_pool() -> str:
    """The mount folder of the first pool Kiboto made or took in that is here now ("" before any)."""
    for row in _pool_rows():  # oldest first
        mp = row.get("mountpoint") or ""
        if not row.get("ejected") and mp and os.path.ismount(mp):
            return mp
    return ""


def on_it(path: str, rows: list[dict[str, Any]] | None = None) -> bool:
    """A folder of a managed host that is on none of its pools. A pool that is away still counts:
    its folder is on that pool, not on the system disk."""
    if not path or not applies():
        return False
    real = os.path.realpath(path)
    for row in _pool_rows() if rows is None else rows:
        mp = os.path.realpath(row.get("mountpoint") or "/")
        if not row.get("ejected") and mp != "/" and (real == mp or real.startswith(mp + "/")):
            return False
    return True


def new_share_problem(path: str) -> tuple[str, str] | None:
    """Why a new shared folder can't be at path (ON_SYSTEM_DISK), or None."""
    return ON_SYSTEM_DISK if on_it(path) else None


def default_folder(name: str) -> str:
    """Where a new share goes when no folder was chosen: on the first pool ("" before there is one)."""
    pool = first_pool()
    return os.path.join(pool, name) if pool else ""


def default_share_after_pool(adapter: Any, have_shares: bool) -> str:
    """After the first pool is made: the shared folder every install starts with, on that pool.
    "" when there are shares already (or elsewhere than a managed host)."""
    if have_shares or not applies() or not first_pool():
        return ""
    adapter.create_share(name=DEFAULT_SHARE, path="", comment="Kiboto storage", security="private")
    return DEFAULT_SHARE


def usage() -> dict[str, Any]:
    """How full the system disk is, for the This machine card."""
    try:
        u = shutil.disk_usage("/")
    except OSError:
        return {}
    return {"total_bytes": u.total, "free_bytes": u.free}
