"""The pools this system is expected to have.

Kiboto writes a pool down when it makes or imports one: its name, kind, the file system's own id,
its drives and where it is mounted. The record answers three things the tools cannot once a pool is
not there: that it should be (so it is listed as missing, with an alert, and not forgotten), how to
bring it back at start (btrfs and ext4 pools are mounted by nothing else), and that it was ejected
on purpose (so it is neither mounted again nor reported).

A pool's folder is also made unwritable while nothing is mounted on it, so that a share or an app
writing there when the pool is away fails at once and does not fill the system disk."""

import json
import os
import time
from collections.abc import Callable
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json

Runner = Callable[[list[str]], tuple[int, str, str]]
KINDS = ("zfs", "btrfs", "ext4", "xfs")  # xfs: only ever imported, never made
BTRFS_SURVIVES_A_DRIVE = ("raid1", "raid1c3", "raid1c4", "raid10")


def _file() -> str:
    return os.path.join(DATA_DIR, "storage", "pools.json")


def load() -> list[dict[str, Any]]:
    """Every recorded pool, oldest first. A file that cannot be read is no pools, and says so."""
    try:
        with open(_file(), encoding="utf-8") as f:
            rows = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        logger.error("[Storage] The record of pools could not be read: %s", e)
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("name") and r.get("fs_type") in KINDS]


def _save(rows: list[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(_file()), exist_ok=True)
    atomic_write_json(_file(), rows, indent=1)


def find(name: str) -> dict[str, Any] | None:
    return next((r for r in load() if r["name"] == name), None)


def record(
    name: str,
    fs_type: str,
    profile: str,
    uuid: str,
    members: list[str],
    mountpoint: str,
    options: str = "",
    origin: str = "created",
) -> dict[str, Any]:
    """Writes a pool down, in place of an older record of the same name."""
    row = {
        "name": name,
        "fs_type": fs_type,
        "profile": profile,
        "uuid": uuid,
        "members": list(members),
        "mountpoint": mountpoint,
        "options": options,
        "origin": origin,
        "ejected": False,
        "recorded_at": time.time(),
    }
    _save([r for r in load() if r["name"] != name] + [row])
    return row


def forget(name: str) -> bool:
    rows = load()
    kept = [r for r in rows if r["name"] != name]
    if len(kept) != len(rows):
        _save(kept)
    return len(kept) != len(rows)


def set_ejected(name: str, ejected: bool) -> None:
    """An ejected pool is away on purpose: not mounted at start, not listed as missing."""
    rows = load()
    for r in rows:
        if r["name"] == name and bool(r.get("ejected")) != ejected:
            r["ejected"] = ejected
            _save(rows)
            return


def rename(old: str, new: str) -> None:
    rows = load()
    for r in rows:
        if r["name"] == old:
            r["name"] = new
            _save(rows)
            return


def read_uuid(fs_type: str, name: str, device: str, run: Runner) -> str:
    """The id the file system gave itself: a ZFS pool's guid, else the UUID on the first drive."""
    if fs_type == "zfs":
        code, out, _ = run(["zpool", "get", "-Hp", "-o", "value", "guid", name])
    else:
        code, out, _ = run(["blkid", "-o", "value", "-s", "UUID", device])
    return out.strip() if code == 0 else ""


def is_there(row: dict[str, Any], run: Runner) -> bool:
    """True when this very pool is in use now: imported (ZFS) or mounted on its folder."""
    if row["fs_type"] == "zfs":
        code, out, _ = run(["zpool", "get", "-Hp", "-o", "value", "guid", row["name"]])
        return code == 0 and (not row.get("uuid") or out.strip() == row["uuid"])
    code, out, _ = run(["findmnt", "-rno", "UUID", "-M", row["mountpoint"]])
    return code == 0 and bool(out.strip()) and (not row.get("uuid") or out.strip() == row["uuid"])


def protect(mountpoint: str, run: Runner) -> None:
    """Makes the empty folder a pool is mounted on unwritable, for the time nothing is mounted there.
    Where the file system below has no such flag, the folder stays as it is."""
    try:
        if os.path.ismount(mountpoint) or os.listdir(mountpoint):
            return
    except OSError:
        return
    code, _, err = run(["chattr", "+i", mountpoint])
    if code != 0:
        logger.info("[Storage] %s could not be made unwritable while empty: %s", mountpoint, err)


def unprotect(mountpoint: str, run: Runner) -> None:
    if os.path.isdir(mountpoint) and not os.path.ismount(mountpoint):
        run(["chattr", "-i", mountpoint])


def bring_back(row: dict[str, Any], run: Runner) -> str:
    """Imports or mounts one recorded pool. "" when it is there afterwards, else why not."""
    if is_there(row, run):
        return ""
    if not row.get("uuid"):
        return "its record has no id to find it by"
    if row["fs_type"] == "zfs":
        code, out, err = run(["zpool", "import", row["uuid"]])
        return "" if code == 0 else (err or out or "zpool import failed").strip()
    mp = row["mountpoint"]
    try:
        os.makedirs(mp, exist_ok=True)
    except OSError as e:
        return str(e)
    protect(mp, run)
    if row["fs_type"] == "btrfs":
        run(["btrfs", "device", "scan"])  # all drives of a pool must be known before it mounts
    cmd = ["mount"] + (["-o", row["options"]] if row.get("options") else []) + [f"UUID={row['uuid']}", mp]
    code, out, err = run(cmd)
    if code != 0 and row["fs_type"] == "btrfs" and row.get("profile") in BTRFS_SURVIVES_A_DRIVE:
        # A mirror with a drive gone is what a mirror is for: its files stay readable. Read-only, so
        # nothing is written that the repair would have to sort out; the pool then shows as degraded.
        opts = ",".join(x for x in (row.get("options"), "degraded", "ro") if x)
        code2, _out2, _err2 = run(["mount", "-o", opts, f"UUID={row['uuid']}", mp])
        if code2 == 0:
            logger.warning("[Storage] Pool %s is mounted read-only with a drive missing", row["name"])
            return ""
    return "" if code == 0 else (err or out or "mount failed").strip()


def bring_back_all(run: Runner) -> dict[str, str]:
    """At start: every expected pool that is not there is imported or mounted. {name: "" or why not}."""
    done: dict[str, str] = {}
    for row in load():
        if row.get("ejected"):
            continue
        why = bring_back(row, run)
        done[row["name"]] = why
        if why:
            logger.error("[Storage] Pool %s is not there and could not be brought back: %s", row["name"], why)
        else:
            logger.info("[Storage] Pool %s is there", row["name"])
    return done
