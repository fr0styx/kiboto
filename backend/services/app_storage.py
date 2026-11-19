"""How much space each app uses (re-audit 19 Nov 2026, R4).

"What filled my disk?" for apps: the program itself (its image), what it wrote inside the
container, its Docker volumes, and its own folders on the NAS. Docker knows the first three
(GET /system/df, nothing is walked). The folders are only measured when asked: a folder on a
sleeping drive is left alone and said to be asleep, shared media folders are not an app's data
and are not counted, and the walk stops at a time limit and says so.
"""

import os
import time
from typing import Any

from backend.services.app_backup import BULK_STORAGE_PREFIXES, SYSTEM_MOUNT_PREFIXES

WALK_SECONDS = 20.0  # all folders together


def _under(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == p or path.startswith(p + "/") for p in prefixes)


def folder_size(path: str, deadline: float) -> tuple[int, bool]:
    """(bytes, complete) of a folder without following links; stops at the deadline."""
    total = 0
    stack = [path]
    while stack:
        if time.monotonic() > deadline:
            return total, False
        try:
            with os.scandir(stack.pop()) as entries:
                for e in entries:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total, True


def _asleep(path: str) -> bool:
    from backend.services.rag_standby import is_backing_disk_in_standby, resolve_path_backing_dev

    try:
        return bool(is_backing_disk_in_standby(resolve_path_backing_dev(path)))
    except (OSError, ValueError, RuntimeError):
        return True  # cannot tell: do not risk waking it


def _name(c: dict[str, Any]) -> str:
    return ((c.get("Names") or [""])[0]).lstrip("/") or str(c.get("Id", ""))[:12]


def summarize(df: dict[str, Any], walk: bool = False, asleep=_asleep, now=time.monotonic) -> dict[str, Any]:
    """One row per app from Docker's own numbers; with walk, its folders on the NAS are measured."""
    images = {i.get("Id"): int(i.get("Size") or 0) for i in df.get("Images") or []}
    volumes = {v.get("Name"): int((v.get("UsageData") or {}).get("Size") or 0) for v in df.get("Volumes") or []}
    deadline = now() + WALK_SECONDS
    seen_folders: set[str] = set()
    apps = []
    for c in df.get("Containers") or []:
        labels = c.get("Labels") or {}
        folders, shared, volume_bytes = [], 0, 0
        for m in c.get("Mounts") or []:
            if m.get("Type") == "volume":
                volume_bytes += max(0, volumes.get(m.get("Name"), 0))
                continue
            src = str(m.get("Source") or "")
            if m.get("Type") != "bind" or not src or _under(src, SYSTEM_MOUNT_PREFIXES):
                continue
            if _under(src, BULK_STORAGE_PREFIXES):
                shared += 1  # a shared folder the app reads: not the app's own data
                continue
            entry: dict[str, Any] = {"path": src, "bytes": None, "state": "not_measured"}
            if src in seen_folders:
                entry["state"] = "counted_elsewhere"  # two apps share it: counted once
            elif walk:
                seen_folders.add(src)
                if not os.path.isdir(src):
                    entry["state"] = "missing"
                elif asleep(src):
                    entry["state"] = "asleep"
                else:
                    size, complete = folder_size(src, deadline)
                    entry.update(bytes=size, state="measured" if complete else "partial")
            folders.append(entry)
        written = max(0, int(c.get("SizeRw") or 0))
        data = written + volume_bytes + sum(f["bytes"] or 0 for f in folders)
        apps.append(
            {
                "name": _name(c),
                "stack": labels.get("com.docker.compose.project") or "",
                "running": str(c.get("State", "")).lower() == "running",
                "program_bytes": images.get(c.get("ImageID"), 0),
                "written_bytes": written,
                "volumes_bytes": volume_bytes,
                "folders": folders,
                "shared_folders": shared,
                "data_bytes": data,
            }
        )
    apps.sort(key=lambda a: (-a["data_bytes"], -a["program_bytes"], a["name"]))
    return {"apps": apps, "folders_measured": walk, "total_data_bytes": sum(a["data_bytes"] for a in apps)}


def measure(walk: bool = False) -> dict[str, Any]:
    """Raises RuntimeError when Docker does not answer or refuses."""
    from backend.services import docker_client

    try:
        status, df = docker_client.request("GET", "/system/df", timeout=60.0)
    except docker_client.DockerUnavailable as e:
        raise RuntimeError(e.message or "Docker is not running") from e
    if status != 200 or not isinstance(df, dict):
        message = df.get("message") if isinstance(df, dict) else ""
        raise RuntimeError(message or f"Docker answered {status}")
    return summarize(df, walk)
