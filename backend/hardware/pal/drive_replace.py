"""Replacing a drive of a pool from the app, where Kiboto manages the pools (Kiboto OS, plain Linux).

The pool rebuilds onto the new drive with its own tool while it stays in use: ZFS with
`zpool replace`, btrfs with `btrfs replace start`. Only a pool that keeps a second copy of every
file can do that (a ZFS mirror or RAIDZ; btrfs RAID1, RAID1C3/4, RAID10, RAID5/6). A pool on one
drive, or one that spreads files without a copy, cannot: its files come back from a backup.

The new drive must be empty: a whole drive with no partitions, no file system, nothing mounted,
and at least as large as the one it replaces. Nothing is erased to make room.

`run` is the adapter's command runner: (code, stdout, stderr)."""

import json
import os
import re
from collections.abc import Callable
from typing import Any

Run = Callable[[list[str]], tuple[int, str, str]]
REDUNDANT_ZFS = re.compile(r"^(mirror|raidz[123]?)(-\d+)?$")
REDUNDANT_BTRFS = {"raid1", "raid1c3", "raid1c4", "raid10", "raid5", "raid6"}
_POOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}$")


class ReplaceError(ValueError):
    """Why a replacement is not started; `key` names the sentence for the screen."""

    def __init__(self, key: str, message: str):
        super().__init__(message)
        self.key = key


# --- the drives -----------------------------------------------------------------------------------
def free_drives(run: Run, at_least: int = 0) -> list[dict[str, Any]]:
    """Whole drives that hold nothing: no partition, no file system, not mounted. Sorted by size."""
    code, out, _ = run(["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,TYPE,FSTYPE,MOUNTPOINT,SERIAL,MODEL,ROTA,RO"])
    if code != 0:
        return []
    try:
        devices = json.loads(out or "{}").get("blockdevices") or []
    except ValueError:
        return []
    found = []
    for d in devices:
        if d.get("type") != "disk" or d.get("children") or d.get("fstype") or d.get("mountpoint"):
            continue
        if str(d.get("ro")) in ("1", "True", "true") or str(d.get("name", "")).startswith(("zram", "loop")):
            continue
        size = int(d.get("size") or 0)
        if size < max(at_least, 1):
            continue
        found.append(
            {
                "dev": d.get("name") or "",
                "path": d.get("path") or "",
                "size_bytes": size,
                "serial": d.get("serial") or "",
                "model": (d.get("model") or "").strip(),
                "rotational": str(d.get("rota")) in ("1", "True", "true"),
            }
        )
    return sorted(found, key=lambda d: d["size_bytes"])


def by_id(path: str, root: str = "/dev/disk/by-id") -> str:
    """The drive's lasting name (/dev/disk/by-id/...), so a pool never loses it when /dev names move."""
    real = os.path.realpath(path)
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return path
    ranked = sorted(
        (n for n in names if not re.search(r"-part\d+$", n) and os.path.realpath(os.path.join(root, n)) == real),
        key=lambda n: (not n.startswith("wwn-"), not n.startswith(("ata-", "nvme-", "scsi-")), n),
    )
    return os.path.join(root, ranked[0]) if ranked else path


# --- what each kind of pool says about its drives -------------------------------------------------
def zfs_leaves(status: str) -> tuple[list[dict[str, Any]], bool]:
    """The drives of a pool from `zpool status -P`: each with its state, the group it is in and
    the section (data, logs, cache, spares); and whether every data group keeps copies (a mirror,
    RAIDZ or dRAID). A missing drive shows as a number, with the path it "was"."""
    rows, in_config = [], False
    for line in status.splitlines():
        if re.match(r"^\s*NAME\s+STATE", line):
            in_config = True
            continue
        if not in_config:
            continue
        if not line.strip() or line.startswith("errors:"):
            if rows:
                break
            continue
        body = line.lstrip("\t")
        rows.append((len(body) - len(body.lstrip(" ")), body.split(), line))
    if not rows:
        return [], False
    top = rows[0][0]
    leaves: list[dict[str, Any]] = []
    groups: list[str] = []
    section, group = "data", ""
    for depth, parts, line in rows[1:]:
        name, state = parts[0], parts[1] if len(parts) > 1 else ""
        level = depth - top
        if level <= 0:  # logs, cache, spares, special, dedup
            section, group = name, ""
            continue
        if level == 2 and (REDUNDANT_ZFS.match(name) or name.startswith("draid")):
            group = name
            if section == "data":
                groups.append(name)
            continue
        if level == 2:  # a drive straight under the pool: its files have no copy
            group = ""
            if section == "data":
                groups.append("")
        was = re.search(r"was (\S+)", line)
        leaves.append(
            {"name": name, "state": state, "group": group, "section": section, "was": was.group(1) if was else ""}
        )
    copies = bool(groups) and all(g and (REDUNDANT_ZFS.match(g) or g.startswith("draid")) for g in groups)
    return leaves, copies


def btrfs_devices(show: str) -> list[dict[str, Any]]:
    """The devices of a btrfs pool from `btrfs filesystem show --raw`; a missing one has no path."""
    out = []
    for line in show.splitlines():
        m = re.search(r"devid\s+(\d+)\s+size\s+(\d+)\s+used\s+\d+\s+path\s+(\S+)(.*)$", line)
        if m:
            missing = "MISSING" in m.group(4) or m.group(3).startswith("<")
            out.append(
                {
                    "devid": int(m.group(1)),
                    "size_bytes": int(m.group(2)),
                    "path": "" if missing else m.group(3),
                    "missing": missing,
                }
            )
    return out


def btrfs_profile(df: str) -> str:
    """The data profile from `btrfs filesystem df`: "raid1", "single", ..."""
    m = re.search(r"^Data,\s*([A-Za-z0-9]+)", df, re.M)
    return m.group(1).lower() if m else ""


# --- the plan, the start, the progress ------------------------------------------------------------
def zfs_progress(status: str) -> dict[str, Any]:
    m = re.search(r"resilver in progress.*?(\d+(?:\.\d+)?)% done", status, re.S)
    if m:
        return {"running": True, "percent": float(m.group(1))}
    return {"running": "resilver in progress" in status, "percent": None}


def btrfs_progress(said: str) -> dict[str, Any]:
    m = re.search(r"(\d+(?:\.\d+)?)% done", said)
    if m and "finished" not in said.lower():
        return {"running": True, "percent": float(m.group(1))}
    return {"running": False, "percent": 100.0 if "finished" in said.lower() else None}


def plan(pool: Any, run: Run) -> dict[str, Any]:
    """What the screen offers for a pool: whether it can rebuild onto a new drive, its drives with
    their state, the empty drives that would fit, and a replacement that is running now."""
    fs = str(getattr(pool, "fs_type", "") or "")
    base: dict[str, Any] = {
        "pool": pool.id,
        "fs": fs,
        "can": False,
        "why": "",
        "members": [],
        "drives": [],
        "progress": {"running": False, "percent": None},
    }
    if fs == "zfs":
        name = _zfs_name(pool)
        code, out, err = run(["zpool", "status", "-P", name])
        if code != 0:
            return {**base, "why": "no_status"}
        leaves, copies = zfs_leaves(out)
        sizes = _sizes(run)
        members = [
            {
                "id": leaf["name"],
                "label": leaf["was"] or leaf["name"],
                "state": leaf["state"],
                "size_bytes": sizes.get(os.path.realpath(_whole(leaf["name"])), 0),
            }
            for leaf in leaves
            if leaf["section"] == "data"
        ]
        progress = zfs_progress(out)
    elif fs == "btrfs":
        mount = str(getattr(pool, "mountpoint", "") or "")
        code, out, _ = run(["btrfs", "filesystem", "show", "--raw", mount])
        code2, df, _ = run(["btrfs", "filesystem", "df", mount])
        if code != 0 or code2 != 0:
            return {**base, "why": "no_status"}
        copies = btrfs_profile(df) in REDUNDANT_BTRFS
        members = [
            {
                "id": str(d["devid"]),
                "label": d["path"] or f"missing drive {d['devid']}",
                "state": "MISSING" if d["missing"] else "ONLINE",
                "size_bytes": d["size_bytes"],
            }
            for d in btrfs_devices(out)
        ]
        progress = btrfs_progress(run(["btrfs", "replace", "status", "-1", mount])[1])
    else:
        return {**base, "why": "one_drive"}  # ext4 and the like: one drive, no copy to rebuild from
    if not copies:
        return {**base, "members": members, "why": "no_copy"}
    smallest = min((m["size_bytes"] for m in members if m["size_bytes"]), default=0)
    return {**base, "can": True, "members": members, "drives": free_drives(run, smallest), "progress": progress}


def start(pool: Any, old: str, new: str, run: Run) -> dict[str, Any]:
    """Starts rebuilding `old` (a member id from plan) onto the empty drive `new` (a path from plan)."""
    p = plan(pool, run)
    if not p["can"]:
        raise ReplaceError(p["why"] or "no_copy", "This pool cannot rebuild onto a new drive.")
    if p["progress"]["running"]:
        raise ReplaceError("busy", "A drive of this pool is being replaced already.")
    member = next((m for m in p["members"] if m["id"] == old), None)
    if member is None:
        raise ReplaceError("no_member", "That drive is not one of this pool's drives.")
    drive = next((d for d in p["drives"] if d["path"] == new), None)
    if drive is None:
        raise ReplaceError("not_free", "That drive is not an empty drive large enough for this pool.")
    target = by_id(drive["path"])
    if p["fs"] == "zfs":
        cmd = ["zpool", "replace", _zfs_name(pool), old, target]
    else:
        cmd = ["btrfs", "replace", "start", "-f", old, target, str(pool.mountpoint)]
    code, out, err = run(cmd)
    if code != 0:
        lines = (err or out or "").strip().splitlines()
        raise ReplaceError("failed", lines[-1][:300] if lines else "The pool's tool refused the replacement.")
    return {"started": True, "pool": pool.id, "old": member["label"], "new": target}


def _zfs_name(pool: Any) -> str:
    name = str(getattr(pool, "id", "") or "")
    name = name.split(":", 1)[1] if name.startswith(("zfs:", "zpool:")) else name
    if not _POOL_NAME.match(name):
        raise ReplaceError("no_member", "That is not a pool name.")
    return name


def _whole(path: str) -> str:
    """/dev/disk/by-id/x-part1 -> /dev/disk/by-id/x: the drive a partition is on."""
    return re.sub(r"-part\d+$", "", path)


def _sizes(run: Run) -> dict[str, int]:
    code, out, _ = run(["lsblk", "-J", "-b", "-d", "-o", "PATH,SIZE"])
    if code != 0:
        return {}
    try:
        return {
            os.path.realpath(d["path"]): int(d.get("size") or 0)
            for d in json.loads(out).get("blockdevices") or []
            if d.get("path")
        }
    except (ValueError, KeyError, TypeError):
        return {}
