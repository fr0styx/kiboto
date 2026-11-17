"""How well this NAS is protected (FEAT-01): its copies outside the box, the newest good one and
where they are, for the Overview; and where a new one could go, for "Protect this NAS".

A copy counts as outside the box when it is on a cloud remote, a USB disk or another NAS (a
network mount, or replication over SSH). A copy on another pool of the same NAS doesn't: a fire,
a theft or a power surge takes both.
"""

import os
import time
from typing import Any

from backend.config import logger

FRESH_SECS = 3 * 86400  # newer than this, a copy is current
USB_ROOT = "/mnt/disks"
NAS_ROOTS = ("/mnt/remotes", "/mnt/addons")


# Destinations on another machine that restic reaches itself. A backup buddy is the first one
# ("rest:http://..."): it counted as "here", so a household that backs up to a second Kiboto
# was told it has no copy outside (SET-06).
OTHER_MACHINE = ("rest:", "sftp:")


def kind_of(location: str) -> str:
    """ "cloud", "usb", "nas" or "here" for a backup destination. The one rule for "is this copy
    outside the box": the Overview and "Getting started" both ask here."""
    if location.startswith("rclone:"):
        return "cloud"
    if location.startswith(OTHER_MACHINE):
        return "nas"
    if location.startswith(USB_ROOT + "/"):
        return "usb"
    if location.startswith(tuple(r + "/" for r in NAS_ROOTS)):
        return "nas"
    return "here"


def copies() -> list[dict[str, Any]]:
    """Every backup that puts the files outside this NAS, with when it last succeeded."""
    out: list[dict[str, Any]] = []
    try:
        from backend.services.offsite_backup import list_repos

        for r in list_repos():
            kind = kind_of(str(r.get("location") or ""))
            if kind != "here":
                out.append(
                    {
                        "name": r.get("name") or r.get("id"),
                        "kind": kind,
                        "engine": "offsite",
                        "last_ok": r.get("last_backup"),
                    }
                )
    except Exception:
        logger.debug("protection_status: off-site backups unreadable", exc_info=True)
    try:
        from backend.services.backup_engine import get_backup_jobs

        for j in get_backup_jobs():
            moved = j.get("migrated_to") and j.get("enabled") is False  # still on until its successor ran
            if j.get("kind") == "config" or j.get("destination_type") != "remote" or moved:
                continue
            out.append({"name": j.get("name"), "kind": "cloud", "engine": "copy", "last_ok": j.get("last_success_at")})
    except Exception:
        logger.debug("protection_status: copy jobs unreadable", exc_info=True)
    try:
        from backend.services.replication_engine import get_replication_engine

        for j in get_replication_engine().list_jobs():
            if j.get("target_type", "local") != "local":
                out.append(
                    {"name": j.get("name"), "kind": "nas", "engine": "replication", "last_ok": j.get("last_success")}
                )
    except Exception:
        logger.debug("protection_status: replication jobs unreadable", exc_info=True)
    return out


def status(now: float | None = None) -> dict[str, Any]:
    """ "good" (a current copy outside the box), "stale" (only older ones) or "none"."""
    now = now or time.time()
    found = copies()
    good = [c for c in found if c.get("last_ok")]
    fresh = [c for c in good if now - float(c["last_ok"]) <= FRESH_SECS]
    level = "good" if fresh else "stale" if found else "none"
    return {
        "level": level,
        "copies": len(fresh),
        "total": len(found),
        "last_good": max((float(c["last_ok"]) for c in good), default=None),
        "where": sorted({c["kind"] for c in fresh}),
        "items": found,
        "recycle_bytes": _recycle_bytes(),
    }


def _recycle_bytes() -> int:
    try:
        from backend.services.recycle_bin import total_bytes

        return total_bytes()
    except Exception:
        logger.debug("protection_status: recycle bin index unreadable", exc_info=True)
        return 0


def _mounted(root: str) -> list[str]:
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [p for p in (os.path.join(root, n) for n in names) if os.path.ismount(p)]


def destinations() -> dict[str, list[str]]:
    """Where a new backup could go: USB disks, network mounts and cloud remotes set up here."""
    cloud: list[str] = []
    try:
        from backend.services.rclone_engine import get_rclone_engine

        cloud = [
            str(r.get("name"))
            for r in get_rclone_engine().list_remotes()
            if r.get("name") and not str(r.get("name")).startswith("crypt_")
        ]
    except Exception:
        logger.debug("protection_status: rclone remotes unreadable", exc_info=True)
    return {"usb": _mounted(USB_ROOT), "nas": [p for root in NAS_ROOTS for p in _mounted(root)], "cloud": cloud}


# Backup 5: which shared folders have a copy outside this NAS. A folder can be left out on purpose
# (a scratch or download folder); the list of those is kept here, apart from the backups.
LEFT_OUT_FILE_NAME = "backup_left_out.json"


def _left_out_file() -> str:
    from backend.config import DATA_DIR

    return os.path.join(DATA_DIR, LEFT_OUT_FILE_NAME)


def left_out() -> list[str]:
    from backend.fsutil import read_json

    data = read_json(_left_out_file(), [])
    return [str(n) for n in data] if isinstance(data, list) else []


def set_left_out(name: str, on: bool) -> list[str]:
    from backend.fsutil import atomic_write_json, locked_json

    with locked_json(_left_out_file()):
        names = [n for n in left_out() if n != name]
        if on:
            names.append(name)
        atomic_write_json(_left_out_file(), sorted(names))
    return sorted(names)


def _copy_sources(pool_path: Any = None) -> list[dict[str, Any]]:
    """Each copy outside this NAS with the folders it reads: off-site backups, copy jobs to a remote
    and replication to another NAS."""
    out: list[dict[str, Any]] = []
    try:
        from backend.services.offsite_backup import list_repos

        for r in list_repos():
            if kind_of(str(r.get("location") or "")) != "here":
                out.append(
                    {
                        "name": r.get("name") or r.get("id"),
                        "paths": list(r.get("paths") or []),
                        "last_ok": r.get("last_backup"),
                    }
                )
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ImportError, RuntimeError):
        logger.debug("protection_status: off-site backups unreadable", exc_info=True)
    if pool_path is None:
        from backend.hardware.pal_storage import get_storage_platform

        pool_path = get_storage_platform().get_pool_path
    try:
        from backend.services.backup_engine import get_backup_jobs

        for j in get_backup_jobs():
            if j.get("kind") == "config" or j.get("destination_type") != "remote" or j.get("enabled") is False:
                continue
            base = str(pool_path(j.get("source_pool", "default")) or "")
            sub = str(j.get("source_subvolume") or "").strip("/")
            paths = [os.path.join(base, "@shares", sub), os.path.join(base, sub)] if sub else [base]
            out.append({"name": j.get("name"), "paths": [p for p in paths if p], "last_ok": j.get("last_success_at")})
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ImportError, RuntimeError):
        logger.debug("protection_status: copy jobs unreadable", exc_info=True)
    try:
        from backend.services.replication_engine import get_replication_engine

        for j in get_replication_engine().list_jobs():
            if j.get("target_type", "local") == "local":
                continue
            base = str(pool_path(j.get("source_pool", "")) or "")
            path = os.path.join(base, str(j.get("source_dataset") or "").strip("/")) if base else ""
            out.append({"name": j.get("name"), "paths": [path] if path else [], "last_ok": j.get("last_success")})
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ImportError, RuntimeError):
        logger.debug("protection_status: replication jobs unreadable", exc_info=True)
    return out


def _inside(child: str, parent: str) -> bool:
    child, parent = os.path.normpath(child), os.path.normpath(parent)
    return child == parent or child.startswith(parent.rstrip("/") + "/")


def folder_coverage(shares: list[dict[str, Any]], sources: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Per shared folder: the copies that hold all of it, those that hold part of it, and whether it
    was left out on purpose."""
    sources = _copy_sources() if sources is None else sources
    skipped = set(left_out())
    rows = []
    for share in shares:
        path = str(share.get("path") or "")
        whole, part = [], []
        for src in sources:
            paths = [p for p in src.get("paths") or [] if p]
            if any(_inside(path, p) for p in paths):
                whole.append({"name": src.get("name"), "last_ok": src.get("last_ok")})
            elif any(_inside(p, path) for p in paths):
                part.append({"name": src.get("name"), "last_ok": src.get("last_ok")})
        rows.append(
            {
                "name": share.get("name"),
                "path": path,
                "copies": whole,
                "partly": part,
                "left_out": share.get("name") in skipped,
            }
        )
    return rows
