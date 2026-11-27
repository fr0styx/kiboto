"""What a request about a pool may name: checked by the API and again by the host door (ADR 0006),
which runs what changes the machine and so does not take the web process's word for it."""

from __future__ import annotations

import os
import re

from backend import config

# a pool as the storage tools name it; they get it as an argument: no leading dash, no spaces
POOL_ID_PATTERN = r"^[A-Za-z0-9_/][A-Za-z0-9_./:-]{0,127}$"
# a pool's name, or its new one: one folder name under the pool root, no dash first
POOL_NAME_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$"
NEW_POOL_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]{0,31}$"  # a pool Kiboto makes
KINDS_MADE = ("btrfs", "zfs", "ext4")

# The layouts each kind of pool is made with, and the drives each needs. Other names for the same
# layout lead to it ("raid1" is a ZFS mirror); any other name is refused. Before, ZFS took "raid1"
# (the API's default), "raid10" or "raid5" and made a stripe with no copy that its record then
# called protected, and ext4 recorded "raid1" for its one drive.
LAYOUTS = {
    "zfs": {"single": 1, "mirror": 2, "raidz1": 3, "raidz2": 4, "raidz3": 5},
    "btrfs": {"single": 1, "raid0": 2, "raid1": 2, "raid1c3": 3, "raid1c4": 4, "raid10": 4},
    "ext4": {"single": 1},
}
_SAME_LAYOUT = {
    "zfs": {"raid1": "mirror", "stripe": "single", "raid0": "single"},
    "btrfs": {"mirror": "raid1", "jbod": "single"},
}
_ZFS_SAYS = {
    "mirror": "OpenZFS Mirror requires at least 2 disks",
    "raidz1": "OpenZFS RAIDZ1 requires at least 3 disks (single parity)",
    "raidz2": "OpenZFS RAIDZ2 requires at least 4 disks (dual parity)",
    "raidz3": "OpenZFS RAIDZ3 requires at least 5 disks (triple parity)",
}


def pool_layout(fs_type: str, profile: str, drives: int) -> str:
    """The layout a new pool is made with, by the name its record keeps: one the kind of pool has,
    on enough drives. ext4 is one drive."""
    fs = (fs_type or "").lower()
    if fs not in LAYOUTS:
        raise ValueError("Kiboto makes ZFS, btrfs and ext4 pools.")
    asked = (profile or "").lower()
    layout = _SAME_LAYOUT.get(fs, {}).get(asked, asked)
    if layout not in LAYOUTS[fs]:
        names = ", ".join(LAYOUTS[fs])
        raise ValueError(f"A new {fs} pool is made as one of: {names}. Not {profile or 'nothing'}.")
    if fs == "ext4" and drives > 1:
        raise ValueError("ext4 is made on one drive. To use more drives together, choose ZFS or btrfs.")
    if drives < LAYOUTS[fs][layout]:
        raise ValueError(
            _ZFS_SAYS.get(layout, "")
            if fs == "zfs"
            else f"{layout.upper()} requires at least {LAYOUTS[fs][layout]} disks"
        )
    return layout


def pool_id(value: str) -> str:
    """A pool's id as the storage tools take it. A leading / is refused too: ids are names (a
    ZFS pool, a device, a folder's name), never a path."""
    if not re.match(POOL_ID_PATTERN, value or "") or value.startswith("/") or ".." in value.split("/"):
        raise ValueError("pool_id must be a pool's name")
    return value


def pool_name(value: str) -> str:
    if not re.match(POOL_NAME_PATTERN, value or ""):
        raise ValueError("A pool's name: letters, digits, '.', '-' and '_', not starting with '-' or '.'.")
    return value


def new_pool_name(value: str) -> str:
    if not re.match(NEW_POOL_PATTERN, value or ""):
        raise ValueError("Pool name: letters, digits, - and _ (max 32), starting with a letter.")
    return value


def new_pool_mount(value: str | None) -> str:
    """Where a new pool is mounted: "" (the pool root's own folder for it) or a folder inside the
    pool root, as its real path."""
    v = (value or "").strip()
    if not v:
        return ""
    root = os.path.realpath(getattr(config, "POOL_PATH", "") or "/mnt")
    real = os.path.realpath(v)
    if not real.startswith(root.rstrip("/") + "/") or re.search(r"[\x00-\x1f,]", v):
        raise ValueError(f"The mount point must be inside {root}.")
    return real


def import_mount(value: str | None) -> str | None:
    """Where an imported pool may be mounted: under /mnt, /srv or /media and not Kiboto's own
    folders (a filesystem mounted over /etc or the data folder would hide it)."""
    v = (value or "").strip()
    if not v:
        return None
    from backend.fsutil import is_protected

    real = os.path.realpath(v)
    if not os.path.isabs(v) or not real.startswith(("/mnt/", "/srv/", "/media/")) or is_protected(real):
        raise ValueError("Mount an imported pool in a folder under /mnt, /srv or /media.")
    return real
