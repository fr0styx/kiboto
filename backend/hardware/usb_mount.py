"""USB disks on a machine set up for Kiboto: listed when plugged in, opened when someone asks.

On Unraid a plug-in (Unassigned Devices) mounts USB disks under /mnt/disks, where the USB card,
backups to a USB disk and the camera import look for them (services/usb_copy.py). A machine set
up for Kiboto has no such plug-in, so a plugged-in disk never showed up. Kiboto lists the USB
disks it could open from lsblk (udev's record: no disk is read), mounts one under /mnt/disks when
someone asks, and ejects it. Nothing is mounted by itself. Disks of a pool, RAID, ZFS, LVM or
encryption members and the system disk are never offered."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from typing import Any

from backend.config import logger

ROOT = "/mnt/disks"
KINDS = {"vfat", "exfat", "ntfs", "ext4", "ext3", "ext2", "btrfs", "xfs"}
LSBLK = ["lsblk", "-J", "-b", "-o", "NAME,PATH,TRAN,HOTPLUG,TYPE,FSTYPE,LABEL,UUID,SIZE,MOUNTPOINTS"]
Runner = Callable[[list[str]], tuple[int, str, str]]


def run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)
    return p.returncode, p.stdout, p.stderr


def _mounts(node: dict[str, Any]) -> list[str]:
    return [m for m in (node.get("mountpoints") or []) if m]


def _pool_devices() -> set[str]:
    from backend.hardware.pal import pool_registry

    found: set[str] = set()
    for row in pool_registry.load():
        found.update(str(d) for d in row.get("disks") or [])
        if row.get("uuid"):
            found.add(f"uuid:{row['uuid']}")
    return found


def unmounted(do: Runner | None = None) -> list[dict[str, Any]]:
    """USB disks (or their partitions) with a file system Kiboto can open that are not mounted."""
    code, out, _ = (do or run)(LSBLK)
    if code:
        return []
    try:
        tree = json.loads(out or "{}").get("blockdevices") or []
    except ValueError:
        return []
    pools = _pool_devices()
    found = []
    for disk in tree:
        if disk.get("type") != "disk" or not (disk.get("tran") == "usb" or disk.get("hotplug")):
            continue
        parts = disk.get("children") or [disk]
        if any(m and not m.startswith(ROOT + "/") for p in parts for m in _mounts(p)):
            continue  # some of it is in use elsewhere (the system, a pool)
        for p in parts:
            fs = str(p.get("fstype") or "")
            if fs not in KINDS or _mounts(p) or p.get("path") in pools or f"uuid:{p.get('uuid')}" in pools:
                continue
            found.append(
                {"device": p["path"], "label": p.get("label") or "", "fs": fs, "size_bytes": int(p.get("size") or 0)}
            )
    return found


def _target(disk: dict[str, Any]) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", disk["label"]).strip("._-") or os.path.basename(disk["device"])
    target, n = os.path.join(ROOT, base), 2
    while os.path.ismount(target) or (os.path.exists(target) and os.listdir(target)):
        target, n = os.path.join(ROOT, f"{base}-{n}"), n + 1
    return target


def open_disk(device: str, do: Runner | None = None) -> str:
    """Mounts a listed USB disk under /mnt/disks and returns where."""
    do = do or run
    disk = next((d for d in unmounted(do) if d["device"] == device), None)
    if disk is None:
        raise ValueError("That is not a USB disk Kiboto can open here.")
    target = _target(disk)
    os.makedirs(target, exist_ok=True)
    opts = "nosuid,nodev,noexec"
    if disk["fs"] in ("vfat", "exfat"):
        opts += ",uid=0,gid=100,umask=0002"  # no owners of their own: the users group may write
    cmd = ["mount", "-o", opts] + (["-t", "ntfs3"] if disk["fs"] == "ntfs" else []) + [device, target]
    code, out, err = do(cmd)
    if code:
        _drop_folder(target)
        raise RuntimeError(f"The disk could not be opened: {(err or out).strip() or 'mount failed'}")
    return target


def eject(path: str, do: Runner | None = None) -> None:
    """Unmounts a USB disk opened under /mnt/disks, after everything is written to it."""
    do = do or run
    real = os.path.realpath(path)
    if os.path.dirname(real) != ROOT or not os.path.ismount(real):
        raise ValueError("That is not an open USB disk.")
    do(["sync"])
    code, out, err = do(["umount", real])
    if code:
        raise RuntimeError(f"The disk is still in use, so it was not ejected: {(err or out).strip()}")
    _drop_folder(real)


def _drop_folder(path: str) -> None:
    try:
        os.rmdir(path)
    except OSError as e:  # something was left in it: the folder stays
        logger.debug("[USB] %s kept: %s", path, e)
