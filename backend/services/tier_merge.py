"""A shared folder that shows two pools as one (data tiering on Kiboto's own pools, owner's
decision 19 Nov 2026: build it now, with a change to the install file).

On a system where Kiboto manages the pools, a shared folder lives on one pool. For its old files
to move to a slower pool and still show in the same folder, the folder becomes a merged one:

  - its own files move (one rename, nothing is copied) to a hidden folder beside it on the same
    pool, `.kiboto-tier/<name>`: the fast side;
  - the slow side is `.kiboto-tier/<name>` on the slower pool;
  - at the folder's own path, where everyone finds it, the two are shown as one (mergerfs).

The merge runs in a container of its own beside Kiboto (kiboto-merge), so restarting or updating
Kiboto does not interrupt it. What it mounts has to be seen by Kiboto and by the container that
serves SMB: that needs shared mounts in the install file (docker-compose.linux.yml). Where they
are missing, a folder is not offered.

While the merge is not running the folder's path is an empty folder nobody can write to; the
files are safe in the two hidden folders. Tried with throwaway containers only: there is no
Kiboto-managed machine to try it on."""

import hashlib
import os
import shlex
import shutil
import socket
import threading
import time
from typing import Any

from backend import legacy_names, merged_folders, product
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked
from backend.merged_folders import merges, of

CONF_DIR = os.path.join(DATA_DIR, "merge")
CONF_NAME = "merge.sh"
CONTAINER = "kiboto-merge"
HIDDEN = ".kiboto-tier"
TOOL = "mergerfs"
# new files go to the first side (the fast one); nothing is cached, so a file the mover has just
# moved is found on the other side at once
OPTIONS = "allow_other,category.create=ff,cache.files=off,fsname=kiboto-tier"
MOUNT_WAIT_SECS = 60.0
UNMOUNT_WAIT_SECS = 30.0
ELEVATED = {"X-Kiboto-Elevated": "1"}
MOUNTINFO = "/proc/self/mountinfo"
FUSE = "/dev/fuse"
SMB_CONTAINERS = ("kiboto-samba", legacy_names.OLD_SAMBA)  # the one that serves SMB, by either name
ASK_EVERY_SECS = 30.0

_lock = threading.Lock()
_asked: dict[str, Any] = {"at": 0.0, "said": None}


class MergeError(RuntimeError):
    """Something that cannot be done; `key` names the sentence for the screen."""

    def __init__(self, key: str, message: str):
        super().__init__(message)
        self.key = key


# --- what is kept: backend/merged_folders.py reads the list, for snapshots and pools too -------------
def sides(path: str, slow_mount: str) -> tuple[str, str]:
    """The fast and the slow side of a shared folder: hidden folders on its own pool and on the slower one."""
    path = path.rstrip("/")
    name = os.path.basename(path)
    return os.path.join(os.path.dirname(path), HIDDEN, name), os.path.join(slow_mount.rstrip("/"), HIDDEN, name)


# --- what the system has to offer ------------------------------------------------------------------
def _mounts() -> list[dict[str, str]]:
    out = []
    try:
        with open(MOUNTINFO, encoding="utf-8", errors="replace") as f:
            for line in f:
                left, _, right = line.partition(" - ")
                fields, kind = left.split(), right.split()
                if len(fields) >= 6 and kind:
                    place = fields[4].replace("\\040", " ")
                    out.append({"at": place, "tags": " ".join(fields[6:]), "fs": kind[0]})
    except OSError:
        logger.debug("[Merge] the mounts could not be read", exc_info=True)
    return out


def receives_mounts(path: str) -> bool:
    """True when a mount made on the host under this path shows up here (a shared or slave mount)."""
    best = ""
    tags = ""
    for m in _mounts():
        at = m["at"].rstrip("/") or "/"
        if (path == at or path.startswith(at.rstrip("/") + "/")) and len(at) >= len(best):
            best, tags = at, m["tags"]
    return "master:" in tags or "shared:" in tags


def mounted(path: str) -> bool:
    """True when the merge is mounted at the folder's path and answers, as seen from here. A merge
    whose program died is still listed as a mount, and every look at it fails."""
    path = path.rstrip("/")
    if not any(m["at"].rstrip("/") == path and m["fs"].startswith("fuse") for m in _mounts()):
        return False
    try:
        os.stat(path)
    except OSError:
        return False
    return True


def _docker(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, Any]:
    from backend.services.container_mutator import docker_request

    try:
        return docker_request(method, path, body=body, headers=headers)
    except (OSError, RuntimeError):
        logger.debug("[Merge] Docker did not answer %s %s", method, path, exc_info=True)
        return 0, None


def _self() -> dict[str, Any]:
    for ref in (socket.gethostname(), *legacy_names.app_container_names()[:2]):
        code, info = _docker("GET", f"/containers/{ref}/json")
        if code == 200 and isinstance(info, dict):
            return info
    return {}


def _engine() -> dict[str, Any]:
    """What the app engine says about Kiboto and the container that serves SMB, asked at most every
    half minute: {"me": bool, "smb": its mounts, or None when there is no such container}."""
    now = time.time()
    if now - _asked["at"] < ASK_EVERY_SECS and _asked["said"]:
        return _asked["said"]
    said: dict[str, Any] = {"me": bool(_self()), "smb": None}
    for ref in SMB_CONTAINERS:
        code, info = _docker("GET", f"/containers/{ref}/json")
        if code == 200 and isinstance(info, dict):
            said["smb"] = [
                (str(m.get("Destination") or "").rstrip("/"), str(m.get("Propagation") or ""))
                for m in info.get("Mounts") or []
            ]
            break
    _asked.update(at=now, said=said)
    return said


def _smb_sees(path: str, smb: list[tuple[str, str]] | None) -> bool:
    """True when the container that serves SMB gets the mounts made under this path (or there is none)."""
    if smb is None:
        return True
    for inside, passed_on in smb:
        if inside and (path == inside or path.startswith(inside + "/")):
            return passed_on in ("rslave", "rshared", "slave", "shared")
    return False  # it does not have the folder at all


def missing(path: str) -> str:
    """Why a merged folder cannot be made at this path on this system; "" when it can."""
    if not shutil.which(TOOL):
        return "no_tool"
    if not os.path.exists(FUSE):
        return "no_fuse"
    if not receives_mounts(path):
        return "not_shared"
    engine = _engine()
    if not engine["me"]:
        return "no_engine"
    if not _smb_sees(path, engine["smb"]):
        return "smb_not_shared"
    return ""


# --- the container that keeps the merges mounted ---------------------------------------------------
def script(kept: list[dict[str, Any]]) -> str:
    """The helper's program: one merge per folder, unmounted again when it is asked to stop."""
    lines = [
        "#!/bin/sh",
        "# Written by Kiboto: the merged folders. Do not edit; it is written again on every change.",
        'pids=""',
        "merge() {",
        '  umount -l "$3" 2>/dev/null  # one left behind by a merge that was killed',
        f'  {TOOL} -f -o {OPTIONS} "$1:$2" "$3" &',
        '  pids="$pids $!"',
        "}",
        'stop() { for p in $pids; do kill "$p" 2>/dev/null; done; wait; exit "$1"; }',
        "trap 'stop 0' TERM INT",
    ]
    for m in sorted(kept, key=lambda m: m["path"]):
        lines.append(f"merge {shlex.quote(m['fast'])} {shlex.quote(m['slow'])} {shlex.quote(m['path'])}")
    lines += [
        "# one of them died: end with an error, so the container is started again and mounts all anew",
        "while :; do",
        '  for p in $pids; do kill -0 "$p" 2>/dev/null || stop 1; done',
        "  sleep 5 &",
        "  wait $!",
        "done",
        "",
    ]
    return "\n".join(lines)


def _roots(me: dict[str, Any], kept: list[dict[str, Any]]) -> dict[str, str] | None:
    """Kiboto's own mounts that hold the merges' folders: {path here: path on the host}."""
    roots: dict[str, str] = {}
    for m in kept:
        for place in (m["path"], m["slow"]):
            best: tuple[str, str] | None = None
            for mount in me.get("Mounts") or []:
                inside, outside = str(mount.get("Destination") or "").rstrip("/"), str(mount.get("Source") or "")
                if inside and outside and (place == inside or place.startswith(inside + "/")):
                    if best is None or len(inside) > len(best[0]):
                        best = (inside, outside)
            if best is None:
                return None
            roots[best[0]] = best[1]
    return roots


def desired(me: dict[str, Any], kept: list[dict[str, Any]], conf_hash: str) -> dict[str, Any] | None:
    """The container: Kiboto's image, the pools at the paths Kiboto knows them by (what it mounts
    there is passed on to the host), the right to mount, no network."""
    from backend.services.iscsi_target import host_path

    roots, conf = _roots(me, kept), host_path(me, CONF_DIR)
    if roots is None or conf is None:
        return None
    return {
        "Image": (me.get("Config") or {}).get("Image") or product.IMAGE + ":latest",
        "Entrypoint": ["sh"],
        "Cmd": [f"/conf/{CONF_NAME}"],
        "Healthcheck": {"Test": ["NONE"]},
        "Labels": {"app": CONTAINER, "managed-by": product.CONTAINER, "kiboto.conf": conf_hash},
        "HostConfig": {
            "NetworkMode": "none",
            "RestartPolicy": {"Name": "unless-stopped"},
            "CapAdd": ["SYS_ADMIN"],
            "SecurityOpt": ["apparmor=unconfined"],
            "Devices": [{"PathOnHost": "/dev/fuse", "PathInContainer": "/dev/fuse", "CgroupPermissions": "rwm"}],
            "Binds": [f"{conf}:/conf:ro"],
            "Mounts": [
                {"Type": "bind", "Source": outside, "Target": inside, "BindOptions": {"Propagation": "rshared"}}
                for inside, outside in sorted(roots.items())
            ],
        },
    }


def ensure() -> str:
    """Makes the container match the merges that are kept: none, no container. Returns "" or why not."""
    kept = merges()
    text = script(kept)
    conf_hash = hashlib.sha256((text + OPTIONS).encode()).hexdigest()[:16]
    code, info = _docker("GET", f"/containers/{CONTAINER}/json")
    there = code == 200 and isinstance(info, dict)
    if not kept:
        if there:
            _docker("POST", f"/containers/{CONTAINER}/stop?t=20")
            _docker("DELETE", f"/containers/{CONTAINER}?force=true")
        return ""
    running = there and bool(((info or {}).get("State") or {}).get("Running"))
    same = there and (((info or {}).get("Config") or {}).get("Labels") or {}).get("kiboto.conf") == conf_hash
    if running and same:
        return ""
    me = _self()
    want = desired(me, kept, conf_hash) if me else None
    if want is None:
        return "no_engine" if not me else "no_path"
    os.makedirs(CONF_DIR, mode=0o700, exist_ok=True)
    target = os.path.join(CONF_DIR, CONF_NAME)
    with open(target + ".new", "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(target + ".new", 0o700)
    os.replace(target + ".new", target)
    if there:
        _docker("POST", f"/containers/{CONTAINER}/stop?t=20")  # it unmounts what it mounted
        _docker("DELETE", f"/containers/{CONTAINER}?force=true")
    created, said = _docker("POST", f"/containers/create?name={CONTAINER}", want, ELEVATED)
    started, said = _docker("POST", f"/containers/{CONTAINER}/start") if created in (200, 201) else (0, said)
    if started not in (200, 204, 304):
        logger.warning("[Merge] %s did not start: %s %s", CONTAINER, created, said)
        return "no_start"
    logger.info("[Merge] %s keeps %d merged folder(s) mounted", CONTAINER, len(kept))
    return ""


def ensure_soon() -> None:
    def work() -> None:
        try:
            ensure()
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("[Merge] could not start the merged folders", exc_info=True)

    if merges():
        threading.Thread(target=work, name="tier-merge", daemon=True).start()


def _wait(path: str, want: bool, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if mounted(path) == want:
            return True
        time.sleep(0.5)
    return mounted(path) == want


# --- making a folder a merged one, and back --------------------------------------------------------
@json_locked(lambda *a, **k: merged_folders.STATE_FILE)
def _keep(merge: dict[str, Any], there: bool) -> None:
    """Writes the list with this merge in it, or without it."""
    kept = [m for m in merges() if m["path"] != merge["path"]]
    atomic_write_json(merged_folders.STATE_FILE, {"merges": [*kept, merge] if there else kept})


def add(name: str, path: str, slow_mount: str, slow_pool: str) -> dict[str, Any]:
    """Makes the shared folder at `path` a merged one with a slow side on the pool mounted at
    `slow_mount`. The folder is away for a few seconds. On any failure it is put back as it was."""
    path = path.rstrip("/")
    with _lock:
        if of(path) is not None:
            return of(path) or {}
        fast, slow = sides(path, slow_mount)
        if ":" in fast + slow + path:
            raise MergeError("bad_name", "A folder with a colon in its path cannot be merged.")
        if not os.path.isdir(path) or os.path.islink(path) or os.path.ismount(path):
            raise MergeError("not_plain", "This shared folder is a mount of its own or a link: it cannot be merged.")
        same_pool = path.startswith(slow_mount.rstrip("/") + "/")
        if not os.path.isdir(slow_mount) or os.path.lexists(fast) or same_pool:
            raise MergeError("bad_sides", "The slower pool cannot be used for this folder.")
        why = missing(path)
        if why:
            raise MergeError(why, "This system cannot show two pools as one folder yet.")
        like = os.stat(path)
        os.makedirs(os.path.dirname(fast), mode=0o755, exist_ok=True)
        os.makedirs(os.path.dirname(slow), mode=0o755, exist_ok=True)
        if not os.path.isdir(slow):
            os.mkdir(slow)
            os.chown(slow, like.st_uid, like.st_gid)
            os.chmod(slow, like.st_mode & 0o7777)
        merge = {"name": name, "path": path, "fast": fast, "slow": slow, "slow_pool": slow_pool, "made": time.time()}
        os.rename(path, fast)  # the folder's own files: one rename on the same pool
        try:
            os.mkdir(path, 0o000)  # nobody writes here while the merge is not mounted
            os.chown(path, like.st_uid, like.st_gid)
            _keep(merge, True)
            why = ensure()
            if why or not _wait(path, True, MOUNT_WAIT_SECS):
                raise MergeError(why or "no_mount", "The merged folder did not come up.")
        except (OSError, MergeError) as e:
            _undo(merge)
            if isinstance(e, MergeError):
                raise
            raise MergeError("failed", f"The folder could not be merged: {e.strerror or e}") from e
        logger.info("[Merge] %s now shows %s and %s as one", path, fast, slow)
        return merge


def _undo(merge: dict[str, Any]) -> bool:
    """Puts a folder back as it was: the merge gone, its own files at its path again. Only when the
    path can be freed; otherwise everything stays recorded as merged. Returns whether it was undone."""
    path, fast = merge["path"], merge["fast"]
    _keep(merge, False)
    ensure()
    if not _wait(path, False, UNMOUNT_WAIT_SECS):
        _keep(merge, True)  # still mounted: it stays a merged folder
        ensure()
        return False
    try:
        if os.path.isdir(path):
            os.rmdir(path)
        os.rename(fast, path)
    except OSError:
        logger.warning("[Merge] %s could not be put back; its files are in %s", path, fast, exc_info=True)
        return False
    _tidy(os.path.dirname(fast))
    return True


def _tidy(hidden: str) -> None:
    """Removes a pool's hidden folder once no merged folder has a side in it."""
    try:
        if os.path.basename(hidden) == HIDDEN and not any(os.scandir(hidden)):
            os.rmdir(hidden)
    except OSError:
        logger.debug("[Merge] %s was left in place", hidden, exc_info=True)


def remove_if_empty(path: str) -> bool:
    """Tiering was turned off for the folder: when nothing is on its slow side, it becomes an
    ordinary folder again. With files there it stays merged, so they keep showing."""
    with _lock:
        merge = of(path)
        if merge is None:
            return True
        try:
            if any(os.scandir(merge["slow"])):
                return False
        except OSError:
            return False
        if not _undo(merge):
            return False
        try:
            os.rmdir(merge["slow"])
        except OSError:
            logger.debug("[Merge] %s was left in place", merge["slow"], exc_info=True)
        _tidy(os.path.dirname(merge["slow"]))
        return True


def status() -> list[dict[str, Any]]:
    """Each merged folder, and whether its merge is mounted right now."""
    return [{**m, "mounted": mounted(m["path"])} for m in merges()]
