"""Disks for other computers over the network: iSCSI (owner's decision, 19 Nov 2026).

A "disk" here is a file in one of the NAS's folders that another computer uses as if it were a
drive of its own: a virtualisation host for its virtual machines, a PC for a games library, a
backup program that wants a disk. Off until an administrator turns it on.

The service is tgtd, a small program that speaks iSCSI itself, in a container of its own beside
Kiboto (like the name service): it needs nothing loaded into the system's kernel, only the
network port and the folders the disks are in. Every disk has a user name and a password (CHAP);
there is no disk anyone on the network can open. A disk can also be limited to one address."""

import hashlib
import ipaddress
import json
import os
import re
import shlex
import socket
import threading
import time
import uuid
from typing import Any

from backend import legacy_names, product, runtime
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json, resolve_within
from backend.secret_box import seal, unseal
from backend.services.path_access import ALLOWED_BROWSE_ROOTS

STATE_FILE = os.path.join(DATA_DIR, "iscsi.json")
CONF_DIR = os.path.join(DATA_DIR, "iscsi")
CONF_NAME = "setup.sh"
CONTAINER = "kiboto-iscsi"
PORT = 3260
IQN_PREFIX = "iqn.2026-11.net.kiboto"
MAX_DISKS = 8
MIN_GB, MAX_GB = 1, 64 * 1024
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
USER = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
SECRET = re.compile(r"^[\x21-\x7e]{12,16}$")  # what every initiator accepts: 12 to 16 printable characters, no spaces
FILE_SUFFIX = ".iscsi.img"
ELEVATED = {"X-Kiboto-Elevated": "1"}
NO_DOCKER = "Kiboto could not reach the app engine, so the iSCSI service was not started."

_lock = threading.Lock()


class DiskError(ValueError):
    """What is wrong with a disk as it was sent; `key` names the sentence for the screen."""

    def __init__(self, key: str, message: str, **params: Any):
        super().__init__(message)
        self.key = key
        self.params = params


# --- what is kept -------------------------------------------------------------------------------
def _read() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    data = data if isinstance(data, dict) else {}
    disks = [d for d in data.get("disks") or [] if isinstance(d, dict) and d.get("id") and d.get("name")]
    return {"enabled": bool(data.get("enabled", False)), "disks": disks}


def enabled() -> bool:
    return _read()["enabled"]


def disks() -> list[dict[str, Any]]:
    return _read()["disks"]


def node() -> str:
    """The NAS's name as it appears in each disk's address."""
    from backend.services import nas_name

    return (
        re.sub(r"[^a-z0-9-]", "-", str(nas_name.config().get("name") or "kiboto").lower()).strip("-")[:40] or "kiboto"
    )


def iqn(name: str) -> str:
    """The disk's full iSCSI name, which the other computer is given."""
    return f"{IQN_PREFIX}:{node()}:{name}"


def file_of(disk: dict[str, Any]) -> str:
    return os.path.join(disk["folder"], disk["name"] + FILE_SUFFIX)


def public(disk: dict[str, Any]) -> dict[str, Any]:
    """A disk as the screen may have it: no password, and what its file takes up now."""
    path = file_of(disk)
    try:
        st = os.stat(path)
        used, there = st.st_blocks * 512, True
    except OSError:
        used, there = 0, False
    return {
        "id": disk["id"],
        "name": disk["name"],
        "iqn": iqn(disk["name"]),
        "size_gb": disk["size_gb"],
        "folder": disk["folder"],
        "file": path,
        "file_there": there,
        "used_bytes": used,
        "user": disk["user"],
        "allow": disk.get("allow") or "",
    }


# --- what a disk may be ---------------------------------------------------------------------------
def _clean_allow(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        return str(ipaddress.ip_network(text, strict=False)) if "/" in text else str(ipaddress.ip_address(text))
    except ValueError:
        raise DiskError("bad_allow", "That is not an address such as 192.168.1.20 or 192.168.1.0/24.") from None


def _clean_folder(raw: Any) -> str:
    real = resolve_within(str(raw or "").strip(), ALLOWED_BROWSE_ROOTS)
    if real is None or not os.path.isdir(real) or any(c in real for c in "\n\r"):
        raise DiskError("bad_folder", "That folder is not one of the NAS's shared folders.")
    data = os.path.realpath(DATA_DIR)
    if real == data or real.startswith(data.rstrip(os.sep) + os.sep):
        raise DiskError("bad_folder", "That folder is not one of the NAS's shared folders.")
    return real


def clean(raw: dict[str, Any], old: dict[str, Any] | None = None) -> dict[str, Any]:
    """A disk as it may be kept (the password sealed), or DiskError saying what is wrong.
    A disk that exists keeps its name and folder, can only grow, and keeps its password unless a new one is sent."""
    name = str(raw.get("name") or "").strip().lower() if old is None else old["name"]
    if not NAME.match(name):
        raise DiskError("bad_name", "The name can have small letters, digits and hyphens, up to 31 characters.")
    size = raw.get("size_gb")
    if not isinstance(size, int) or isinstance(size, bool) or not MIN_GB <= size <= MAX_GB:
        raise DiskError("bad_size", f"The size must be between {MIN_GB} and {MAX_GB} GB.", value=MAX_GB)
    if old is not None and size < old["size_gb"]:
        raise DiskError("no_shrink", "A disk can be made larger, never smaller: the other computer's data is on it.")
    user = str(raw.get("user") or "").strip()
    if not USER.match(user):
        raise DiskError("bad_user", "The user name can have letters, digits, dots, hyphens and underscores, up to 32.")
    secret = str(raw.get("secret") or "")
    if secret:
        if not SECRET.match(secret):
            raise DiskError("bad_secret", "The password must be 12 to 16 characters, without spaces.")
        sealed = seal(secret)
    elif old is not None:
        sealed = old["secret"]
    else:
        raise DiskError("bad_secret", "The password must be 12 to 16 characters, without spaces.")
    return {
        "name": name,
        "size_gb": size,
        "folder": old["folder"] if old is not None else _clean_folder(raw.get("folder")),
        "user": user,
        "secret": sealed,
        "allow": _clean_allow(raw.get("allow")),
    }


def _same_password(disk: dict[str, Any], others: list[dict[str, Any]]) -> None:
    """The service knows each user name once: two disks may share one only with the same password."""
    for other in others:
        if other["user"] == disk["user"] and unseal(other["secret"]) != unseal(disk["secret"]):
            raise DiskError(
                "user_taken", "Another disk uses that user name with another password. Choose another user name."
            )


FILE_ERRORS = {
    "file_exists": "There is already a file by that name in the folder.",
    "no_file": "The disk's file could not be made in that folder.",
}


def _make_file_at(path: str, size_gb: int, fresh: bool) -> str:
    """Makes or grows a disk's file. "" when done, else the key of what went wrong. A new one never
    replaces a file that is already there, and it takes no space until the other computer writes."""
    flags = os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0) | (os.O_CREAT | os.O_EXCL if fresh else 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return "file_exists"
    except OSError:
        return "no_file"
    try:
        if os.fstat(fd).st_size < size_gb * 1024**3:
            os.ftruncate(fd, size_gb * 1024**3)
    except OSError:
        return "no_file"
    finally:
        os.close(fd)
    return ""


def _make_file(disk: dict[str, Any], grow_only: bool) -> None:
    """The disk's file at its size; on Kiboto OS the host door makes it (the folders are root's)."""
    if runtime.without_root():
        from backend import door

        key = door.via(
            "iscsi.make_file", make_file_here, path=file_of(disk), size_gb=disk["size_gb"], fresh=not grow_only
        )
    else:
        key = _make_file_at(file_of(disk), disk["size_gb"], not grow_only)
    if key:
        raise DiskError(key, FILE_ERRORS.get(key, FILE_ERRORS["no_file"]))


@json_locked(lambda *a, **k: STATE_FILE)
def set_enabled(on: bool) -> bool:
    data = _read()
    data["enabled"] = bool(on)
    atomic_write_json(STATE_FILE, data)
    return data["enabled"]


@json_locked(lambda *a, **k: STATE_FILE)
def save(raw: dict[str, Any], disk_id: str | None = None) -> dict[str, Any]:
    """Adds a disk (and makes its file), or changes the one with this id. DiskError or KeyError."""
    data = _read()
    if disk_id is None:
        if len(data["disks"]) >= MAX_DISKS:
            raise DiskError("too_many", f"There can be up to {MAX_DISKS} disks.", value=MAX_DISKS)
        fresh = clean(raw)
        if any(d["name"] == fresh["name"] for d in data["disks"]):
            raise DiskError("name_taken", "There is already a disk by that name.")
        _same_password(fresh, data["disks"])
        fresh["id"] = uuid.uuid4().hex[:12]
        fresh["created"] = time.time()
        _make_file(fresh, grow_only=False)
        data["disks"].append(fresh)
    else:
        old = next((d for d in data["disks"] if d["id"] == disk_id), None)
        if old is None:
            raise KeyError(disk_id)
        fresh = {**clean(raw, old), "id": old["id"], "created": old.get("created")}
        _same_password(fresh, [d for d in data["disks"] if d["id"] != disk_id])
        _make_file(fresh, grow_only=True)
        data["disks"][data["disks"].index(old)] = fresh
    atomic_write_json(STATE_FILE, data)
    return fresh


@json_locked(lambda *a, **k: STATE_FILE)
def delete(disk_id: str, with_file: bool = False) -> dict[str, Any] | None:
    """Takes a disk off the list. Its file stays unless `with_file`: it holds another computer's data."""
    data = _read()
    gone = next((d for d in data["disks"] if d["id"] == disk_id), None)
    if gone is None:
        return None
    data["disks"] = [d for d in data["disks"] if d["id"] != disk_id]
    atomic_write_json(STATE_FILE, data)
    if with_file:
        try:
            if runtime.without_root():
                from backend import door

                door.via("iscsi.remove_file", remove_file_here, path=file_of(gone))
            else:
                os.remove(file_of(gone))
        except (OSError, ValueError):
            logger.warning("[iSCSI] the file of %s could not be removed", gone["name"], exc_info=True)
    return gone


# --- the service's own file -----------------------------------------------------------------------
def entry(disk: dict[str, Any]) -> dict[str, str]:
    """A disk as the service needs it, with its password in the clear."""
    return {
        "iqn": iqn(disk["name"]),
        "file": file_of(disk),
        "user": disk["user"],
        "secret": unseal(disk["secret"]),
        "allow": disk.get("allow") or "",
    }


def script_text(entries: list[dict[str, str]]) -> str:
    """What the service is told when it starts: one tgtadm command after another. Each disk, its
    file (written through to the drive before the other computer is told it is saved), who may
    open it and from where. Every value is quoted for the shell."""
    q = shlex.quote
    out = ["#!/bin/sh", "# written by Kiboto; changes made here are lost", "set -e", "t='tgtadm --lld iscsi'"]
    accounts: dict[str, str] = {}
    for tid, e in enumerate(entries, start=1):
        user, secret = e["user"], e["secret"]
        out.append(f"$t --mode target --op new --tid {tid} --targetname {q(e['iqn'])}")
        out.append(f"$t --mode logicalunit --op new --tid {tid} --lun 1 --backing-store {q(e['file'])} --bsoflags sync")
        if user not in accounts:
            accounts[user] = secret
            out.append(f"$t --mode account --op new --user {q(user)} --password {q(secret)}")
        out.append(f"$t --mode account --op bind --tid {tid} --user {q(user)}")
        out.append(f"$t --mode target --op bind --tid {tid} --initiator-address {q(e.get('allow') or 'ALL')}")
    return "\n".join(out) + "\n"


def conf_text(kept: list[dict[str, Any]]) -> str:
    return script_text([entry(d) for d in kept])


def write_conf() -> str:
    """Writes the service's file (it holds the passwords: readable by Kiboto only) and returns its hash."""
    text = conf_text(disks())
    os.makedirs(CONF_DIR, mode=0o700, exist_ok=True)
    path = os.path.join(CONF_DIR, CONF_NAME)
    fd = os.open(path + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(path + ".new", path)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# --- the container --------------------------------------------------------------------------------
SETUP = "/etc/kiboto-iscsi/" + CONF_NAME
START = (
    "tgtd -f & pid=$!; i=0; "
    "until tgtadm --lld iscsi --mode sys --op show >/dev/null 2>&1 || [ $i -ge 50 ]; do i=$((i+1)); sleep 0.2; done; "
    f"sh {SETUP} || exit 1; wait $pid"
)


def _docker(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, Any]:
    from backend.services.container_mutator import docker_request

    try:
        return docker_request(method, path, body=body, headers=headers)
    except (OSError, RuntimeError):
        logger.debug("[iSCSI] Docker did not answer %s %s", method, path, exc_info=True)
        return 0, None


def _self() -> dict[str, Any]:
    for ref in runtime.own_container_refs():
        code, info = _docker("GET", f"/containers/{ref}/json")
        if code == 200 and isinstance(info, dict):
            return info
    return {}


def host_path(me: dict[str, Any], path: str) -> str | None:
    """Where a path Kiboto sees is on the host, from Kiboto's own mounts (the longest that holds it)."""
    best: tuple[int, str] | None = None
    for m in me.get("Mounts") or []:
        inside, outside = str(m.get("Destination") or "").rstrip("/"), str(m.get("Source") or "")
        if not inside or not outside:
            continue
        if path == inside or path.startswith(inside + "/"):
            if best is None or len(inside) > best[0]:
                best = (len(inside), outside.rstrip("/") + path[len(inside) :])
    return best[1] if best else None


def desired(me: dict[str, Any], kept: list[dict[str, Any]], conf_hash: str) -> dict[str, Any] | None:
    """The container: Kiboto's image, tgtd, the host's network, the service's file and the disks'
    folders. None when one of them cannot be found on the host."""
    conf = host_path(me, os.path.join(CONF_DIR, CONF_NAME))
    folders = sorted({d["folder"] for d in kept})
    outside = {f: host_path(me, f) for f in folders}
    if conf is None or any(v is None for v in outside.values()):
        return None
    image = (me.get("Config") or {}).get("Image") or product.IMAGE + ":latest"
    want: dict[str, Any] = {
        "Image": image,
        "Entrypoint": ["sh", "-c"],
        "Cmd": [START],
        "Healthcheck": {"Test": ["NONE"]},
        "HostConfig": {
            "NetworkMode": "host",
            "RestartPolicy": {"Name": "unless-stopped"},
            "ReadonlyRootfs": True,
            "Tmpfs": {"/run": "", "/tmp": ""},
            "Binds": [f"{conf}:{SETUP}:ro", *[f"{outside[f]}:{f}" for f in folders]],
        },
    }
    mark = hashlib.sha256((json.dumps(want, sort_keys=True) + conf_hash).encode()).hexdigest()[:16]
    want["Labels"] = {"app": CONTAINER, "managed-by": product.CONTAINER, "kiboto.config": mark}
    return want


# --- as a service of the machine (runtime.managed_host) --------------------------------------------
UNIT = "kiboto-iscsi"


def _unit(*args: str) -> tuple[int, str]:
    from backend.services.host_basics import run

    return run(list(args), timeout=30)


def _unit_running() -> bool:
    return _unit("systemctl", "is-active", UNIT)[1] == "active"


def unit_command(conf_hash: str, conf: str = "") -> list[str]:
    """tgtd as a unit of the machine, reading the service's file where Kiboto keeps it (on Kiboto OS
    the host door's own copy). The file's hash is in the description, so a change of disks or
    passwords starts it anew."""
    start = START.replace(SETUP, conf or os.path.join(CONF_DIR, CONF_NAME))
    return [
        "systemd-run",
        "--quiet",
        "--collect",
        "--unit",
        UNIT,
        "--description",
        f"Kiboto iSCSI {conf_hash}",
        "-p",
        "Restart=on-failure",
        "-p",
        "RestartSec=5",
        "sh",
        "-c",
        start,
    ]


def _run_unit(cmd: list[str] | None, count: int) -> dict[str, Any]:
    """Starts the unit with `cmd` unless it already runs that very command; stops it for None."""
    running = _unit_running()
    if cmd is None:
        if running:
            _unit("systemctl", "stop", UNIT)
            logger.info("[iSCSI] %s stopped: turned off, or no disk is left", UNIT)
        return {"running": False, "why": ""}
    described = cmd[cmd.index("--description") + 1]
    if running and _unit("systemctl", "show", UNIT, "-p", "Description", "--value")[1] == described:
        return {"running": True, "why": ""}
    _unit("systemctl", "stop", UNIT)
    _unit("systemctl", "reset-failed", UNIT)
    code, said = _unit(*cmd)
    if code != 0:
        logger.warning("[iSCSI] %s could not be started: %s", UNIT, said)
        return {"running": False, "why": "start"}
    logger.info("[iSCSI] %s serves %d disk(s) on port %d", UNIT, count, PORT)
    return {"running": True, "why": ""}


def _ensure_unit(state: dict[str, Any]) -> dict[str, Any]:
    wanted = state["enabled"] and state["disks"]
    if runtime.without_root():  # Kiboto OS: the host door writes the service's file and starts it
        from backend import door

        entries = [entry(d) for d in state["disks"]] if wanted else []
        got = door.via("iscsi.apply", apply_here, disks=entries)
    else:
        got = _run_unit(unit_command(write_conf()) if wanted else None, len(state["disks"]))
    if got.get("why"):
        return status(running=False, error="The iSCSI service could not be started.", why=got["why"])
    return status(running=bool(got.get("running")))


# --- the host door's operations (ADR 0006): nothing is taken from the web process unchecked --------
ROOT_SETUP = "/etc/kiboto/iscsi/" + CONF_NAME  # the door's own copy: root's, and only root reads it
_IQN = re.compile(rf"^{re.escape(IQN_PREFIX)}:[a-z0-9-]{{1,40}}:[a-z0-9][a-z0-9-]{{0,30}}$")


def disk_file(path: Any) -> str:
    """A disk's file as the host door may touch it: in the storage folder, named as Kiboto names
    disk files, reached through no link, never in Kiboto's own folder. ValueError otherwise."""
    from backend.config import POOL_PATH

    text = path if isinstance(path, str) else ""
    name = os.path.basename(text)[: -len(FILE_SUFFIX)] if text.endswith(FILE_SUFFIX) else ""
    real = os.path.realpath(text) if text else ""
    data = os.path.realpath(DATA_DIR).rstrip(os.sep) + os.sep
    if (
        not NAME.match(name)
        or "\n" in text
        or real != os.path.normpath(text)
        or not real.startswith(os.path.realpath(POOL_PATH).rstrip(os.sep) + os.sep)
        or real.startswith(data)
        or (os.path.lexists(real) and not os.path.isfile(real))
    ):
        raise ValueError("Not touching that file: it is not one of Kiboto's iSCSI disk files.")
    return real


def make_file_here(path: str, size_gb: int, fresh: bool) -> str:
    """The host door's operation: makes or grows a disk's file. "" or the key of what went wrong."""
    if isinstance(size_gb, bool) or not isinstance(size_gb, int) or not MIN_GB <= size_gb <= MAX_GB:
        raise ValueError("Not making that file: the size is not one a disk may have.")
    return _make_file_at(disk_file(path), size_gb, bool(fresh))


def remove_file_here(path: str) -> bool:
    """The host door's operation: removes a disk's file (asked for when the disk is deleted)."""
    real = disk_file(path)
    if os.path.lexists(real):
        os.remove(real)
    return True


def _checked(raw: Any) -> dict[str, str]:
    e = raw if isinstance(raw, dict) else {}
    raw_values = {k: e.get(k) for k in ("iqn", "file", "user", "secret", "allow")}
    if not all(isinstance(v, str) for v in raw_values.values()):
        raise ValueError("Not serving: a disk is not described as Kiboto describes it.")
    values: dict[str, str] = {k: str(v) for k, v in raw_values.items()}
    if not _IQN.match(values["iqn"]) or not USER.match(values["user"]) or not SECRET.match(values["secret"]):
        raise ValueError("Not serving: a disk's name, user or password is not one Kiboto allows.")
    try:
        values["allow"] = _clean_allow(values["allow"])
    except DiskError:
        raise ValueError("Not serving: a disk's allowed address is not an address.") from None
    values["file"] = disk_file(values["file"])
    return values


def apply_here(disks: list[Any]) -> dict[str, Any]:
    """The host door's operation: writes its own copy of the service's file from the disks sent,
    each checked, and starts tgtd with it (or stops it when none is sent)."""
    if not isinstance(disks, list) or len(disks) > MAX_DISKS:
        raise ValueError(f"Not serving: there can be up to {MAX_DISKS} disks.")
    entries = [_checked(d) for d in disks]
    if not entries:
        return _run_unit(None, 0)
    text = script_text(entries)
    os.makedirs(os.path.dirname(ROOT_SETUP), mode=0o700, exist_ok=True)
    fd = os.open(ROOT_SETUP + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(ROOT_SETUP + ".new", ROOT_SETUP)
    conf_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return _run_unit(unit_command(conf_hash, ROOT_SETUP), len(entries))


def _remove() -> None:
    _docker("POST", f"/containers/{CONTAINER}/stop?t=5")
    _docker("DELETE", f"/containers/{CONTAINER}?force=true")


def ensure() -> dict[str, Any]:
    """Makes the container match what is kept: started, made anew after a change, or removed."""
    state = _read()
    from backend import runtime

    if runtime.managed_host():  # the machine is Kiboto's: tgtd is a service of it, not a container
        with _lock:
            return _ensure_unit(state)
    with _lock:
        code, info = _docker("GET", f"/containers/{CONTAINER}/json")
        exists = code == 200 and isinstance(info, dict)
        if not state["enabled"] or not state["disks"]:
            if exists:
                _remove()
                logger.info("[iSCSI] %s removed: turned off, or no disk is left", CONTAINER)
            return status(running=False)
        me = _self()
        if not me:
            return status(running=False, error=NO_DOCKER, why="engine")
        want = desired(me, state["disks"], write_conf())
        if want is None:
            return status(running=False, error="A disk's folder is not one the app engine can reach.", why="folder")
        if exists:
            same = ((info.get("Config") or {}).get("Labels") or {}).get("kiboto.config") == want["Labels"][
                "kiboto.config"
            ]
            if same and bool((info.get("State") or {}).get("Running")):
                return status(running=True)
            _remove()
        created, resp = _docker("POST", f"/containers/create?name={CONTAINER}", want, ELEVATED)
        if created not in (200, 201):
            logger.warning("[iSCSI] could not create %s: %s %s", CONTAINER, created, resp)
            return status(running=False, error="The iSCSI service could not be started.", why="start")
        started, _ = _docker("POST", f"/containers/{CONTAINER}/start")
        logger.info("[iSCSI] %s serves %d disk(s) on port %d", CONTAINER, len(state["disks"]), PORT)
        return status(running=started in (200, 204, 304))


def status(running: bool | None = None, error: str = "", why: str = "") -> dict[str, Any]:
    """How the service stands. `why` names the reason it is not running, for the screen's own words:
    engine (no app engine to start it), folder (a disk's folder cannot be handed to it), start, down."""
    state = _read()
    from backend import runtime

    if running is None and runtime.managed_host():  # a service of the machine, not a container
        running = _unit_running()
        if state["enabled"] and state["disks"] and not running:
            error = error or "The iSCSI service is not running. Port 3260 may be in use by another program."
            why = why or "down"
    if running is None:
        code, info = _docker("GET", f"/containers/{CONTAINER}/json")
        box = (info or {}).get("State") or {} if isinstance(info, dict) else {}
        running = code == 200 and bool(box.get("Running")) and not box.get("Restarting")
        if code == 0 and state["enabled"]:
            error, why = error or NO_DOCKER, why or "engine"
        elif state["enabled"] and state["disks"] and not running:
            error = error or "The iSCSI service is not running. Port 3260 may be in use by another program."
            why = why or "down"
    return {
        "enabled": state["enabled"],
        "running": bool(running),
        "port": PORT,
        "error": error,
        "why": why,
        "max_disks": MAX_DISKS,
        "max_gb": MAX_GB,
        "disks": [public(d) for d in state["disks"]],
    }


def ensure_soon() -> None:
    """At startup, on a thread: the app's image may have changed with an update, and after a
    restart of the NAS the service is brought back as it was left."""

    def run() -> None:
        try:
            if enabled():
                ensure()
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("[iSCSI] Could not check the iSCSI service", exc_info=True)

    threading.Thread(target=run, name="iscsi", daemon=True).start()
