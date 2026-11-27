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

import contextlib
import errno
import hashlib
import os
import shlex
import shutil
import socket
import threading
import time
from typing import Any

from backend import legacy_names, merged_folders, product, runtime
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json
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

# Kiboto OS (ADR 0006): the host door keeps its own record of the merges and its own script here,
# and builds the mounts only from those; Kiboto's record beside its data is its copy for the page
DOOR_DIR = "/etc/kiboto/merge"

_lock = threading.Lock()
_asked: dict[str, Any] = {"at": 0.0, "said": None}


class MergeError(RuntimeError):
    """Something that cannot be done; `key` names the sentence for the screen."""

    def __init__(self, key: str, message: str):
        super().__init__(message)
        self.key = key


# --- what is kept: backend/merged_folders.py reads the list, for snapshots and pools too -------------
def _record_file(where: str = "") -> str:
    return os.path.join(where, "merges.json") if where else merged_folders.STATE_FILE


def _kept(where: str = "") -> list[dict[str, Any]]:
    """The merges kept by Kiboto (where="") or by the host door (where=DOOR_DIR)."""
    if not where:
        return merges()
    data = read_json(_record_file(where), {})
    kept = data.get("merges") if isinstance(data, dict) else None
    return [m for m in kept or [] if isinstance(m, dict) and m.get("path") and m.get("fast") and m.get("slow")]


def _of(path: str, where: str = "") -> dict[str, Any] | None:
    path = path.rstrip("/")
    return next((m for m in _kept(where) if m["path"] == path), None)


def sides(path: str, slow_mount: str) -> tuple[str, str]:
    """The fast and the slow side of a shared folder: hidden folders on its own pool and on the slower one."""
    path = path.rstrip("/")
    name = os.path.basename(path)
    return os.path.join(os.path.dirname(path), HIDDEN, name), os.path.join(slow_mount.rstrip("/"), HIDDEN, name)


def _inside(top: str, path: str) -> bool:
    """`path` below `top` is reached through no link on the way. The hidden folders sit at a pool's
    top, where anyone who may write to a share of the whole pool could leave a link in their place,
    and the merge (root's work) would make its folders wherever that led."""
    rest = os.path.relpath(path, top)
    return not rest.startswith("..") and os.path.realpath(path) == os.path.join(os.path.realpath(top), rest)


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
                    source = kind[1] if len(kind) > 1 else ""
                    out.append({"at": place, "tags": " ".join(fields[6:]), "fs": kind[0], "source": source})
    except OSError:
        logger.debug("[Merge] the mounts could not be read", exc_info=True)
    return out


def own_kind(path: str) -> str:
    """How a shared folder sits on its pool, which decides how its own files move to the fast side:
    "folder" and "subvolume" (btrfs) by one rename on the same pool, "dataset" (ZFS) by giving the
    dataset the fast side as its mount point; nothing is copied. "" for a link, a mount of another
    kind, or a folder with a mount inside it: not merged. Before, any folder that was a dataset or
    a subvolume was refused, and Kiboto makes every new shared folder on ZFS and btrfs as one."""
    if not os.path.isdir(path) or os.path.islink(path):
        return ""
    real = os.path.realpath(path).rstrip("/")
    mounts = _mounts()
    if any(m["at"].startswith(real + "/") for m in mounts):
        return ""
    here = [m for m in mounts if m["at"].rstrip("/") == real]
    if here:
        return "dataset" if here[-1]["fs"] == "zfs" and here[-1]["source"] else ""
    if not os.path.ismount(real):
        return "folder"
    try:
        top_of_subvolume = os.stat(real).st_ino == 256
    except OSError:
        return ""
    parent = os.path.dirname(real)
    under = [m for m in mounts if parent == m["at"].rstrip("/") or parent.startswith(m["at"].rstrip("/") + "/")]
    fs = max(under, key=lambda m: len(m["at"]))["fs"] if under else ""
    return "subvolume" if top_of_subvolume and fs == "btrfs" else ""


def _rights_like(path: str, made: str) -> None:
    """The slow side starts with the shared folder's own access lists, not the ones its pool's
    folder hands down."""
    from backend.services import tier_mover

    src = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        dst = os.open(made, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            tier_mover.acls_like(src, dst, folder=True)
        finally:
            os.close(dst)
    finally:
        os.close(src)


def _dataset_at(path: str) -> str:
    real = os.path.realpath(path).rstrip("/")
    return next((m["source"] for m in _mounts() if m["at"].rstrip("/") == real and m["fs"] == "zfs"), "")


def _zfs(*args: str) -> tuple[int, str]:
    from backend.services.host_basics import run

    return run(["zfs", *args], timeout=120)


def _move_away(merge: dict[str, Any], path: str, fast: str) -> None:
    """The folder's own files go to the fast side. OSError when they cannot."""
    if merge["own"] != "dataset":
        os.rename(path, fast)
        return
    code, source = _zfs("get", "-H", "-o", "source", "mountpoint", merge["dataset"])
    merge["mount_was"] = "local" if code == 0 and source.strip() == "local" else "inherited"
    code, said = _zfs("set", f"mountpoint={fast}", merge["dataset"])
    if code != 0:
        raise OSError(errno.EBUSY, said.strip()[:200] or "the dataset was not moved")


def _move_back(merge: dict[str, Any], path: str, fast: str) -> None:
    """The folder's own files at its path again. OSError when they cannot be."""
    if os.path.isdir(path):
        os.rmdir(path)
    if merge.get("own") != "dataset":
        os.rename(fast, path)
        return
    ds = merge["dataset"]
    code, said = _zfs(
        *(("inherit", "mountpoint", ds) if merge.get("mount_was") == "inherited" else ("set", f"mountpoint={path}", ds))
    )
    if code != 0:
        raise OSError(errno.EBUSY, said.strip()[:200] or "the dataset was not moved back")
    with contextlib.suppress(OSError):
        os.rmdir(fast)  # the empty folder ZFS was mounted on


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
    for ref in runtime.own_container_refs():
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
    from backend import runtime

    if runtime.managed_host():  # the machine's own Samba sees the machine's own mounts
        return ""
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


# --- as a service of the machine (runtime.managed_host) --------------------------------------------
UNIT = "kiboto-merge"


def _unit(*args: str) -> tuple[int, str]:
    from backend.services.host_basics import run

    return run(list(args), timeout=60)


def _write_script(text: str, where: str = "") -> str:
    folder = where or CONF_DIR
    os.makedirs(folder, mode=0o700, exist_ok=True)
    target = os.path.join(folder, CONF_NAME)
    with open(target + ".new", "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(target + ".new", 0o700)
    os.replace(target + ".new", target)
    return target


def _ensure_unit(kept: list[dict[str, Any]], text: str, conf_hash: str, where: str = "") -> str:
    """The merges as a unit of the machine: they outlive a restart of Kiboto, and the unit starts
    again when one of them ends (the script then exits with an error)."""
    running = _unit("systemctl", "is-active", UNIT)[1] == "active"
    if not kept:
        if running:
            _unit("systemctl", "stop", UNIT)  # the script unmounts what it mounted
        return ""
    described = f"Kiboto merged folders {conf_hash}"
    if running and _unit("systemctl", "show", UNIT, "-p", "Description", "--value")[1] == described:
        return ""
    target = _write_script(text, where)
    _unit("systemctl", "stop", UNIT)
    _unit("systemctl", "reset-failed", UNIT)
    code, said = _unit(
        "systemd-run", "--quiet", "--collect", "--unit", UNIT, "--description", described,
        "-p", "Restart=on-failure", "-p", "RestartSec=5", "-p", "KillMode=mixed", "sh", target,
    )  # fmt: skip
    if code != 0:
        logger.warning("[Merge] %s did not start: %s", UNIT, said)
        return "no_start"
    logger.info("[Merge] %s keeps %d merged folder(s) mounted", UNIT, len(kept))
    return ""


def ensure(where: str = "") -> str:
    """Makes the container match the merges that are kept: none, no container. Returns "" or why not."""
    if not where and runtime.without_root():  # Kiboto OS: the host door mounts them, from its own record
        from backend import door

        return str(door.via("merge.ensure", ensure_here) or "")
    kept = _kept(where)
    text = script(kept)
    conf_hash = hashlib.sha256((text + OPTIONS).encode()).hexdigest()[:16]
    if runtime.managed_host():  # the machine is Kiboto's: a unit of it, not a container
        return _ensure_unit(kept, text, conf_hash, where)
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
@json_locked(lambda merge, there, where="": _record_file(where))
def _keep(merge: dict[str, Any], there: bool, where: str = "") -> None:
    """Writes the list with this merge in it, or without it."""
    kept = [m for m in _kept(where) if m["path"] != merge["path"]]
    if where:
        os.makedirs(where, mode=0o700, exist_ok=True)
    atomic_write_json(_record_file(where), {"merges": [*kept, merge] if there else kept})


def add(name: str, path: str, slow_mount: str, slow_pool: str, where: str = "") -> dict[str, Any]:
    """Makes the shared folder at `path` a merged one with a slow side on the pool mounted at
    `slow_mount`. The folder is away for a few seconds. On any failure it is put back as it was."""
    path = path.rstrip("/")
    if not where and runtime.without_root():  # Kiboto OS: the folders are root's, the host door does it
        from backend import door

        made = door.via("merge.add", add_here, name=name, path=path, slow_mount=slow_mount, slow_pool=slow_pool)
        if not isinstance(made, dict) or made.get("error"):
            said = made if isinstance(made, dict) else {}
            raise MergeError(
                str(said.get("error") or "failed"), str(said.get("message") or "The folder could not be merged.")
            )
        _keep(made, True)  # Kiboto's copy, for the page, snapshots and pools
        return made
    with _lock:
        if _of(path, where) is not None:
            return _of(path, where) or {}
        fast, slow = sides(path, slow_mount)
        if ":" in fast + slow + path:
            raise MergeError("bad_name", "A folder with a colon in its path cannot be merged.")
        own = own_kind(path)
        if not own:
            raise MergeError("not_plain", "This shared folder is a mount of its own or a link: it cannot be merged.")
        same_pool = path.startswith(slow_mount.rstrip("/") + "/")
        through_link = not _inside(os.path.dirname(path), fast) or not _inside(slow_mount, slow)
        if not os.path.isdir(slow_mount) or os.path.lexists(fast) or same_pool or through_link:
            raise MergeError("bad_sides", "The slower pool cannot be used for this folder.")
        why = missing(path)
        if why:
            raise MergeError(why, "This system cannot show two pools as one folder yet.")
        like = os.stat(path)
        os.makedirs(os.path.dirname(fast), mode=0o755, exist_ok=True)
        os.makedirs(os.path.dirname(slow), mode=0o755, exist_ok=True)
        if not os.path.isdir(slow):
            os.mkdir(slow)
            _rights_like(path, slow)
            os.chown(slow, like.st_uid, like.st_gid)
            os.chmod(slow, like.st_mode & 0o7777)
        merge = {"name": name, "path": path, "fast": fast, "slow": slow, "slow_pool": slow_pool, "made": time.time()}
        merge.update(own=own, **({"dataset": _dataset_at(path)} if own == "dataset" else {}))
        try:
            _move_away(merge, path, fast)
        except OSError as e:
            raise MergeError("failed", f"The folder could not be merged: {e.strerror or e}") from e
        try:
            if os.path.isdir(path):  # ZFS leaves the folder the dataset was mounted on
                os.chmod(path, 0o000)
            else:
                os.mkdir(path, 0o000)  # nobody writes here while the merge is not mounted
            os.chown(path, like.st_uid, like.st_gid)
            _keep(merge, True, where)
            why = ensure(where)
            if why or not _wait(path, True, MOUNT_WAIT_SECS):
                raise MergeError(why or "no_mount", "The merged folder did not come up.")
        except (OSError, MergeError) as e:
            _undo(merge, where)
            if isinstance(e, MergeError):
                raise
            raise MergeError("failed", f"The folder could not be merged: {e.strerror or e}") from e
        logger.info("[Merge] %s now shows %s and %s as one", path, fast, slow)
        return merge


def _undo(merge: dict[str, Any], where: str = "") -> bool:
    """Puts a folder back as it was: the merge gone, its own files at its path again. Only when the
    path can be freed; otherwise everything stays recorded as merged. Returns whether it was undone."""
    path, fast = merge["path"], merge["fast"]
    _keep(merge, False, where)
    ensure(where)
    if not _wait(path, False, UNMOUNT_WAIT_SECS):
        _keep(merge, True, where)  # still mounted: it stays a merged folder
        ensure(where)
        return False
    try:
        _move_back(merge, path, fast)
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


def _holds_files(root: str) -> bool:
    """Whether anything but empty folders is under root (stops at the first; unreadable counts as yes)."""
    try:
        for _here, _dirs, names in os.walk(root, onerror=_raise):
            if names:
                return True
    except OSError:
        return True
    return False


def _raise(e: OSError) -> None:
    raise e


def _drop_empty(root: str) -> None:
    """Removes root and the empty folders in it, deepest first."""
    for here, _dirs, _names in os.walk(root, topdown=False):
        with contextlib.suppress(OSError):
            os.rmdir(here)


def remove_if_empty(path: str, where: str = "") -> bool:
    """Tiering was turned off for the folder: when nothing is on its slow side, it becomes an
    ordinary folder again. With files there it stays merged, so they keep showing."""
    if not where and runtime.without_root():
        from backend import door

        merge = of(path)
        if not door.via("merge.remove", remove_here, path=path.rstrip("/")):
            return False
        if merge is not None:
            _keep(merge, False)
        return True
    with _lock:
        merge = _of(path, where)
        if merge is None:
            return True
        if _holds_files(merge["slow"]):  # folders emptied by hand do not keep it merged
            return False
        if not _undo(merge, where):
            return False
        _drop_empty(merge["slow"])
        _tidy(os.path.dirname(merge["slow"]))
        return True


def status() -> list[dict[str, Any]]:
    """Each merged folder, and whether its merge is mounted right now."""
    return [{**m, "mounted": mounted(m["path"])} for m in merges()]


# --- the host door's operations (ADR 0006): nothing is taken from the web process unchecked --------
def _checked_folder(path: Any) -> str:
    """A shared folder the door may merge: a real folder in the storage folder, reached through no
    link, at least one level inside a pool, never Kiboto's own folder."""
    from backend.config import POOL_PATH

    text = path if isinstance(path, str) else ""
    real = os.path.realpath(text) if text.startswith("/") else ""
    root = os.path.realpath(POOL_PATH).rstrip(os.sep) + os.sep
    data = os.path.realpath(DATA_DIR).rstrip(os.sep) + os.sep
    inside = real[len(root) :] if real.startswith(root) else ""
    if (
        not real
        or real != os.path.normpath(text)
        or inside.count(os.sep) < 1
        or (real + os.sep).startswith(data)
        or "\n" in text
        or not os.path.isdir(real)
    ):
        raise ValueError("Not merging: that is not one of the NAS's shared folders.")
    return real


def add_here(name: str, path: str, slow_mount: str, slow_pool: str) -> dict[str, Any]:
    """The host door's operation: makes a shared folder a merged one, kept in the door's own record.
    The slower pool must be one of this machine's pools, at the place it is mounted."""
    from backend.hardware.pal_storage import get_storage_platform

    real = _checked_folder(path)
    if not isinstance(name, str) or not name or "/" in name or "\n" in name:
        raise ValueError("Not merging: that is not a shared folder's name.")
    mounts = {p.id: (p.mountpoint or "").rstrip("/") for p in get_storage_platform().list_pools()}
    if not slow_mount or mounts.get(slow_pool) != str(slow_mount).rstrip("/"):
        raise ValueError("Not merging: the slower pool is not one of this machine's pools.")
    try:
        return add(name, real, slow_mount, slow_pool, where=DOOR_DIR)
    except MergeError as e:
        return {"error": e.key, "message": str(e)}


def remove_here(path: str) -> bool:
    """The host door's operation: an ordinary folder again, when its slow side is empty."""
    if _of(str(path or ""), DOOR_DIR) is None:
        return True  # the door never merged it: nothing of it to undo
    return remove_if_empty(str(path), where=DOOR_DIR)


def ensure_here() -> str:
    """The host door's operation: the merges of its own record mounted (at Kiboto's start)."""
    return ensure(where=DOOR_DIR)


def door_merges() -> list[dict[str, Any]]:
    """The merges the host door keeps (its own record), for its other operations."""
    return _kept(DOOR_DIR)
