"""People's home folders on the first pool of a machine set up for Kiboto.

The first admin is made at the first start, before there is any pool, and was given a home folder
in the storage folder, which on such a machine is the system disk (hardware/pal/system_disk.py).
Once a pool exists, homes go on it: the place is written down (places.py), and the records of home
folders that were never used (missing or empty) follow it. A home folder with files in it stays.
Settled at every start and after a pool is made.

Virtual machines (their disks, snapshots and settings files) and installer images go on the first
pool the same way, unless machines were already made in the data folder: those stay."""

import os

from backend import config, places
from backend.config import logger
from backend.hardware.pal import system_disk


def settle() -> dict[str, object]:
    if not system_disk.applies() or places.recorded("homes"):
        return {}
    pool = system_disk.first_pool()
    if not pool:
        return {}
    from backend.users_db import move_unused_homes

    new = os.path.join(pool, "homes")
    places.record("homes", new)
    moved = move_unused_homes(os.path.join(config.POOL_PATH, "homes"), new)
    logger.info("[Users] Home folders are made in %s from now on (%s record(s) moved there)", new, moved)
    return {"homes": new, "moved": moved}


def _has_machines(folder: str) -> bool:
    try:
        return any(e != "isos" and os.path.isdir(os.path.join(folder, e)) for e in os.listdir(folder))
    except OSError:
        return False


def vms_root(data_dir: str) -> str:
    """The folder that holds a folder per virtual machine: <data_dir>/vms, or on a managed host with a
    pool <first pool>/vms (chosen once and written down; machines already in the data folder keep it)."""
    default = os.path.join(data_dir, "vms")
    if not system_disk.applies():
        return default
    known = places.recorded("vms")
    if known:
        return known
    pool = system_disk.first_pool()
    if not pool:
        return default
    chosen = default if _has_machines(default) else os.path.join(pool, "vms")
    places.record("vms", chosen)
    logger.info("[VMs] Virtual machines are kept in %s", chosen)
    return chosen


def iso_dir(data_dir: str) -> str:
    """Where installer images go on a managed host with its machines on a pool ("" elsewhere)."""
    root = vms_root(data_dir)
    return os.path.join(root, "isos") if root != os.path.join(data_dir, "vms") else ""
