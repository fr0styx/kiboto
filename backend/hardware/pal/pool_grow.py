"""Adding a drive to a pool from the app, where Kiboto manages the pools (Kiboto OS, plain Linux).

What a pool can take depends on how it is made, and each way is the pool's own tool:

- ZFS, a drive on its own: a second drive makes it a mirror (`zpool attach`): a copy of every
  file, no more space.
- ZFS, mirrors only: two drives make one more mirror beside them (`zpool add ... mirror`): more
  space, every file still kept twice.
- ZFS, RAIDZ: one more drive widens the group (`zpool attach` on the group; ZFS 2.3's RAIDZ
  expansion): more space, the same protection.
- btrfs, one drive: a second drive and a conversion make it a mirror (`btrfs device add`, then a
  balance to RAID1): a copy of every file.
- btrfs: one more drive gives more space (`btrfs device add`; a pool that keeps copies then
  spreads its files with a balance in the background, or the new drive's space stays unused).

The new drives must be empty, as for a replacement (drive_replace.free_drives), and large enough:
nothing is erased to make room. Copying onto them runs in the background while the pool stays in use.

`run` is the adapter's command runner: (code, stdout, stderr)."""

import os
import re
from collections.abc import Callable
from typing import Any

from backend.hardware.pal import drive_replace as dr

Run = Callable[[list[str]], tuple[int, str, str]]
_GROUP = re.compile(r"^(mirror|raidz[123]?)-\d+$")


class GrowError(ValueError):
    """Why a drive is not added; `key` names the sentence for the screen."""

    def __init__(self, key: str, message: str):
        super().__init__(message)
        self.key = key


# --- what is running ------------------------------------------------------------------------------
def zfs_progress(status: str) -> dict[str, Any]:
    """A resilver (after attaching a drive) or a RAIDZ expansion that runs now."""
    if "resilver in progress" in status:
        return dr.zfs_progress(status)
    m = re.search(r"expand:\s+expansion of \S+ in progress.*?(\d+(?:\.\d+)?)% done", status, re.S)
    if m:
        return {"running": True, "percent": float(m.group(1))}
    return {"running": bool(re.search(r"expand:\s+expansion of \S+ in progress", status)), "percent": None}


def btrfs_progress(said: str) -> dict[str, Any]:
    """`btrfs balance status`: "Balance on '/x' is running ... 80% left"."""
    if "is running" not in said and "is paused" not in said:
        return {"running": False, "percent": None}
    m = re.search(r"(\d+(?:\.\d+)?)% left", said)
    return {"running": True, "percent": 100.0 - float(m.group(1)) if m else None}


# --- the plan -------------------------------------------------------------------------------------
def _zfs_groups(status: str) -> list[dict[str, Any]]:
    """The data groups of a pool: a mirror or RAIDZ with its drives, or a drive on its own."""
    leaves, _copies = dr.zfs_leaves(status)
    groups: dict[str, dict[str, Any]] = {}
    for leaf in leaves:
        if leaf["section"] != "data":
            continue
        key = leaf["group"] or f"lone:{leaf['name']}"
        groups.setdefault(key, {"name": leaf["group"] or leaf["name"], "kind": "", "drives": []})
        groups[key]["kind"] = (leaf["group"] or "lone").split("-")[0]
        groups[key]["drives"].append(leaf)
    return list(groups.values())


def _raidz_can_widen(name: str, run: Run) -> bool:
    code, out, _ = run(["zpool", "get", "-H", "-o", "value", "feature@raidz_expansion", name])
    return code == 0 and out.strip() in ("enabled", "active")


def _zfs_ways(pool: Any, run: Run) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    name = dr._zfs_name(pool)
    code, status, _ = run(["zpool", "status", "-P", name])
    if code != 0:
        return [], {"running": False, "percent": None}, "no_status"
    groups = _zfs_groups(status)
    if not groups:
        return [], {"running": False, "percent": None}, "no_status"
    if any(leaf["state"] != "ONLINE" for g in groups for leaf in g["drives"]):
        return [], zfs_progress(status), "not_healthy"
    sizes = dr._sizes(run)

    def size(leaf: dict[str, Any]) -> int:
        return sizes.get(os.path.realpath(dr._whole(leaf["name"])), 0)

    ways = []
    for g in groups:
        if g["kind"] == "lone":
            leaf = g["drives"][0]
            # the pool's record says "mirror" afterwards when this drive was the whole pool
            makes = "mirror" if len(groups) == 1 else ""
            ways.append(
                {
                    "way": "mirror",
                    "to": leaf["name"],
                    "label": leaf["name"],
                    "count": 1,
                    "min": size(leaf),
                    "makes": makes,
                }
            )
        elif g["kind"].startswith("raidz") and _raidz_can_widen(name, run):
            smallest = min((size(leaf) for leaf in g["drives"]), default=0)
            ways.append({"way": "widen", "to": g["name"], "label": g["name"], "count": 1, "min": smallest})
    if all(g["kind"] == "mirror" for g in groups):
        smallest = min((size(leaf) for g in groups for leaf in g["drives"]), default=0)
        ways.append({"way": "add_mirror", "to": "", "label": "", "count": 2, "min": smallest})
    return ways, zfs_progress(status), ""


def _btrfs_ways(pool: Any, run: Run) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    mount = str(getattr(pool, "mountpoint", "") or "")
    code, show, _ = run(["btrfs", "filesystem", "show", "--raw", mount])
    code2, df, _ = run(["btrfs", "filesystem", "df", mount])
    if code != 0 or code2 != 0:
        return [], {"running": False, "percent": None}, "no_status"
    devices = dr.btrfs_devices(show)
    progress = btrfs_progress(run(["btrfs", "balance", "status", mount])[1])
    if not devices or any(d["missing"] for d in devices):
        return [], progress, "not_healthy"
    if dr.btrfs_progress(run(["btrfs", "replace", "status", "-1", mount])[1])["running"]:
        return [], {"running": True, "percent": None}, ""
    profile = dr.btrfs_profile(df)
    smallest = min(d["size_bytes"] for d in devices)
    ways = []
    if profile == "single" and len(devices) == 1:
        ways.append({"way": "mirror", "to": "", "label": devices[0]["path"], "count": 1, "min": smallest})
    ways.append({"way": "add", "to": "", "label": "", "count": 1, "min": 1, "profile": profile})
    return ways, progress, ""


def plan(pool: Any, run: Run) -> dict[str, Any]:
    """What "Add a drive" offers for a pool: the ways it can grow, the empty drives, and copying that runs now."""
    fs = str(getattr(pool, "fs_type", "") or "")
    base: dict[str, Any] = {"pool": pool.id, "fs": fs, "ways": [], "drives": [], "why": "", "progress": {}}
    if fs == "zfs":
        ways, progress, why = _zfs_ways(pool, run)
    elif fs == "btrfs":
        ways, progress, why = _btrfs_ways(pool, run)
    else:
        return {**base, "why": "cannot_grow", "progress": {"running": False, "percent": None}}
    if progress.get("running"):
        return {**base, "progress": progress}
    if why or not ways:
        return {**base, "why": why or "cannot_grow", "progress": progress}
    return {**base, "ways": ways, "drives": dr.free_drives(run), "progress": progress}


# --- adding ---------------------------------------------------------------------------------------
def start(pool: Any, way: str, to: str, drives: list[str], run: Run) -> dict[str, Any]:
    """Adds the empty drives `drives` (paths from plan) the way `way` (with `to`, from plan) says."""
    if getattr(pool, "read_only", False):
        raise GrowError("read_only", "Allow changes to this pool first.")
    p = plan(pool, run)
    if p["progress"].get("running"):
        raise GrowError("busy", "This pool is copying onto a drive already. Add the next one when it has finished.")
    chosen = next((w for w in p["ways"] if w["way"] == way and w["to"] == to), None)
    if chosen is None:
        raise GrowError(p["why"] or "no_way", "This pool cannot take a drive that way.")
    if len(drives) != chosen["count"] or len(set(drives)) != len(drives):
        raise GrowError("count", f"Choose {chosen['count']} different empty drive(s).")
    free = {d["path"]: d for d in p["drives"]}
    for path in drives:
        if path not in free:
            raise GrowError("not_free", "That drive is not an empty drive.")
        if free[path]["size_bytes"] < chosen["min"]:
            raise GrowError("too_small", "That drive is smaller than the pool's drives.")
    targets = [dr.by_id(path) for path in drives]
    if p["fs"] == "zfs":
        _zfs_add(pool, chosen, targets, run)
        profile = str(chosen.get("makes") or "")
    else:
        profile = _btrfs_add(pool, chosen, targets, run)
    return {"started": True, "pool": pool.id, "way": way, "added": targets, "profile": profile}


def _refused(code: int, out: str, err: str, what: str) -> None:
    if code != 0:
        lines = (err or out or "").strip().splitlines()
        raise GrowError("failed", lines[-1][:300] if lines else f"The pool's tool refused to {what}.")


def _zfs_add(pool: Any, way: dict[str, Any], targets: list[str], run: Run) -> None:
    name = dr._zfs_name(pool)
    if way["way"] == "add_mirror":
        cmd = ["zpool", "add", name, "mirror", *targets]  # without -f: ZFS refuses a group unlike the others
    else:
        if not (way["to"].startswith("/dev/") or _GROUP.match(way["to"])):
            raise GrowError("no_way", "That is not one of this pool's drives or groups.")
        cmd = ["zpool", "attach", name, way["to"], targets[0]]
    _refused(*run(cmd), "add the drive")


def _btrfs_add(pool: Any, way: dict[str, Any], targets: list[str], run: Run) -> str:
    """Adds the drive, then starts the balance that makes use of it. Answers the pool's profile now."""
    mount = str(pool.mountpoint)
    _refused(*run(["btrfs", "device", "add", targets[0], mount]), "add the drive")
    if way["way"] == "mirror":
        balance = ["btrfs", "balance", "start", "--bg", "-dconvert=raid1", "-mconvert=raid1", mount]
        profile = "raid1"
    elif way.get("profile") in dr.REDUNDANT_BTRFS:
        balance = ["btrfs", "balance", "start", "--bg", "--full-balance", mount]  # copies need room on two drives
        profile = str(way.get("profile"))
    else:
        return str(way.get("profile") or "single")  # single: new files go to the new drive at once
    code, out, err = run(balance)
    if code != 0:
        lines = (err or out or "").strip().splitlines()
        raise GrowError(
            "balance_failed",
            "The drive was added, but spreading the files over it did not start: "
            + (lines[-1][:200] if lines else "btrfs refused the balance."),
        )
    return profile
