"""Looking into pools that are not in use, without changing them.

After the system disk was replaced the pools are all there, but the new system knows none of
them, and what it needs to know is on them (services/pool_copy.py keeps a copy of the settings on
every pool). So each candidate is opened read-only at a folder of its own under PROBE_ROOT, looked
at, and closed again: a ZFS pool is imported read-only without mounting its datasets, and only its
root dataset is mounted; a btrfs or ext4 file system is mounted read-only without replaying its
journal. Nothing is written to any of them, and none stays open.

`run` is the storage command runner: (code, out, err)."""

import json
import os
import re
import shutil
from collections.abc import Callable
from typing import Any

from backend.config import logger

PROBE_ROOT = "/run/kiboto/probe"
READ_ONLY = {
    "ext4": "ro,noload,nosuid,nodev,noexec",
    "btrfs": "ro,rescue=nologreplay,nosuid,nodev,noexec",
}
_ZFS_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,254}$")
_UUID = re.compile(r"^[0-9A-Fa-f-]{8,40}$")
Runner = Callable[[list[str]], tuple[int, str, str]]


def _zfs_candidates(run: Runner) -> list[dict[str, Any]]:
    code, out, _ = run(["zpool", "import"])
    found: list[dict[str, Any]] = []
    name = ""
    for line in (out if code == 0 else "").splitlines():
        text = line.strip()
        if text.startswith("pool:"):
            name = text.split(":", 1)[1].strip()
        elif text.startswith("id:") and name:
            guid = text.split(":", 1)[1].strip()
            if _ZFS_NAME.match(name) and guid.isdigit():
                found.append({"kind": "zfs", "name": name, "id": guid})
            name = ""
    return found


def _walk(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for node in nodes or []:
        out.append(node)
        out += _walk(node.get("children") or [])
    return out


def _fs_candidates(run: Runner) -> list[dict[str, Any]]:
    """btrfs and ext4 file systems that are mounted nowhere; the drives of one btrfs pool count once."""
    code, out, _ = run(["lsblk", "-J", "-o", "PATH,FSTYPE,UUID,LABEL,MOUNTPOINTS"])
    try:
        nodes = _walk((json.loads(out) if code == 0 else {}).get("blockdevices") or [])
    except ValueError:
        return []
    found: dict[str, dict[str, Any]] = {}
    in_use = {n.get("uuid") for n in nodes if any(n.get("mountpoints") or [])}
    for node in nodes:
        kind, uuid = node.get("fstype"), str(node.get("uuid") or "")
        if kind in READ_ONLY and _UUID.match(uuid) and uuid not in in_use and uuid not in found:
            found[uuid] = {"kind": kind, "name": str(node.get("label") or "")[:64] or uuid[:8], "id": uuid}
    return list(found.values())


def candidates(run: Runner) -> list[dict[str, Any]]:
    """Every pool or file system here that this system is not using: {kind, name, id}."""
    return _zfs_candidates(run) + _fs_candidates(run)


def look_into(found: dict[str, Any], run: Runner, read: Callable[[str], Any]) -> Any:
    """Opens one candidate read-only, hands its root folder to `read`, and closes it again.
    Returns what `read` returned; None when it could not be opened."""
    spot = os.path.join(PROBE_ROOT, re.sub(r"[^A-Za-z0-9]", "", str(found["id"]))[:40] or "x")
    os.makedirs(spot, mode=0o700, exist_ok=True)
    try:
        if found["kind"] == "zfs":
            return _look_into_zfs(found, spot, run, read)
        return _look_into_fs(found, spot, run, read)
    finally:
        shutil.rmtree(spot, ignore_errors=True)  # an empty folder by now: everything below was closed


def _look_into_zfs(found: dict[str, Any], spot: str, run: Runner, read: Callable[[str], Any]) -> Any:
    name = found["name"]
    # -f: the system that used it last is the one that is gone. Read-only, so forcing changes nothing on it.
    code, _, err = run(
        ["zpool", "import", "-f", "-N", "-o", "readonly=on", "-o", "cachefile=none", "-R", spot, found["id"]]
    )
    if code != 0:
        logger.info("[Probe] The ZFS pool %s could not be opened to look into: %s", name, err)
        return None
    try:
        code, where, _ = run(["zfs", "get", "-H", "-o", "value", "mountpoint", name])
        if code != 0 or not where.startswith("/") or run(["zfs", "mount", name])[0] != 0:
            return None
        return read(os.path.join(spot, where.strip().lstrip("/")))
    finally:
        if run(["zpool", "export", name])[0] != 0:
            logger.warning("[Probe] The ZFS pool %s stayed open read-only after looking into it", name)


def _look_into_fs(found: dict[str, Any], spot: str, run: Runner, read: Callable[[str], Any]) -> Any:
    kind = found["kind"]
    if kind == "btrfs":
        run(["btrfs", "device", "scan"])  # all drives of a pool must be known before it mounts
    source = f"UUID={found['id']}"
    code, _, err = run(["mount", "-t", kind, "-o", READ_ONLY[kind], source, spot])
    if code != 0 and kind == "btrfs":  # an older kernel does not know rescue=: plain read-only then
        code, _, err = run(["mount", "-t", kind, "-o", "ro,nosuid,nodev,noexec", source, spot])
    if code != 0:
        logger.info("[Probe] The %s file system %s could not be opened to look into: %s", kind, found["name"], err)
        return None
    try:
        return read(spot)
    finally:
        if run(["umount", spot])[0] != 0:
            run(["umount", "-l", spot])
