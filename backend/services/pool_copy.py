"""A copy of Kiboto's settings on every pool, for the day the system disk fails.

On a machine set up for Kiboto the settings live on the system disk and the files on the pools.
When that disk dies the pools still hold everything but the settings: the people, the shared
folders, the apps, the schedules. So Kiboto keeps a copy of its settings on each of its pools, in
the folder .kiboto at the pool's root: encrypted with the machine's data key, beside that key
wrapped under the recovery key (machine_key.py). The pools and the recovery key are then enough
to bring a machine back.

A pool gets a new copy at most once a day, and never while its drives are asleep: a sleeping pool
keeps the copy it has. A copy that another install left on a pool is not written over. It is
moved aside, into .kiboto/earlier/<its id>/, where it stays until someone removes it."""

import hashlib
import json
import os
import re
import shutil
import threading
import time
from typing import Any

from backend import machine_key, runtime
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

FOLDER = ".kiboto"
ARCHIVE = "settings.kbak"
BEFORE = "settings.kbak.1"  # the copy before this one, in case today's caught a bad day
WRAPPED = "data-key.recovery"
ABOUT = "about.json"
EARLIER = "earlier"
EVERY = 24 * 3600
FORMAT = 1
FOUND = "/run/kiboto/found"  # copies found on the drives, kept in memory until the machine restarts
MAX_ARCHIVE = 256 * 1024 * 1024
ADOPT_FLAG = ".adopt-restored-pools"  # in the data folder: the next start takes the restored pools as its own
_KEY = re.compile(r"^[a-z0-9]{1,16}-[a-z0-9]{1,40}$")
_lock = threading.Lock()


def _state_file() -> str:
    return os.path.join(DATA_DIR, "pool_copy.json")


def _state() -> dict[str, Any]:
    data = read_json(_state_file(), {}) if os.path.exists(_state_file()) else {}
    return data if isinstance(data, dict) else {}


def install_id() -> str:
    """Which install a copy belongs to: made from the data folder's own mark, not the mark itself."""
    from backend.fsutil import data_id

    return hashlib.sha256(b"kiboto:pool-copy:install:" + data_id(DATA_DIR).encode()).hexdigest()[:16]


def passphrase(data_key: str) -> str:
    """What the copy is encrypted with: made from the data key, so the recovery key opens both."""
    return hashlib.sha256(b"kiboto:pool-copy:v1:" + data_key.encode()).hexdigest()


def pools() -> list[dict[str, Any]]:
    """The pools Kiboto made or took in, that are mounted now."""
    from backend.hardware.pal import pool_registry

    return [
        row
        for row in pool_registry.load()
        if not row.get("ejected") and row.get("mountpoint") and os.path.ismount(row["mountpoint"])
    ]


def _disk_of(device: str) -> str:
    """The whole disk a member is on: sdb for /dev/disk/by-id/...-part1."""
    name = os.path.basename(os.path.realpath(device))
    sysfs = os.path.realpath(os.path.join("/sys/class/block", name))
    return os.path.basename(os.path.dirname(sysfs)) if os.path.exists(os.path.join(sysfs, "partition")) else name


def asleep(row: dict[str, Any]) -> bool:
    """True when any drive of the pool is spun down. Asked without waking it."""
    from backend.hardware.disks import is_drive_asleep

    return any(is_drive_asleep(_disk_of(member)) for member in row.get("members") or [])


def _about(folder: str) -> dict[str, Any]:
    data = read_json(os.path.join(folder, ABOUT), {}) if os.path.exists(os.path.join(folder, ABOUT)) else {}
    return data if isinstance(data, dict) else {}


def _set_aside(folder: str, theirs: dict[str, Any]) -> str:
    """A copy another install left here goes into earlier/<its id>/, in place of an older one of that id."""
    their_id = "".join(ch for ch in str(theirs.get("install") or "unknown") if ch.isalnum())[:16] or "unknown"
    aside = os.path.join(folder, EARLIER, their_id)
    shutil.rmtree(aside, ignore_errors=True)
    os.makedirs(aside, mode=0o700)
    for name in (ARCHIVE, BEFORE, WRAPPED, ABOUT):
        if os.path.exists(os.path.join(folder, name)):
            os.replace(os.path.join(folder, name), os.path.join(aside, name))
    return aside


def _put(path: str, data: bytes) -> None:
    tmp = path + ".part"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_one(row: dict[str, Any], archive: bytes, wrapped: bytes, about: dict[str, Any]) -> None:
    folder = os.path.join(row["mountpoint"], FOLDER)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    theirs = _about(folder)
    if theirs and theirs.get("install") != about["install"]:
        logger.info(
            "[PoolCopy] %s holds the settings of another install; kept in %s", row["name"], _set_aside(folder, theirs)
        )
    if os.path.exists(os.path.join(folder, ARCHIVE)):
        os.replace(os.path.join(folder, ARCHIVE), os.path.join(folder, BEFORE))
    _put(os.path.join(folder, ARCHIVE), archive)
    _put(os.path.join(folder, WRAPPED), wrapped)
    _put(os.path.join(folder, ABOUT), json.dumps({**about, "pool": row["name"]}, indent=1).encode())


def _archive(data_key: str) -> bytes:
    from backend.services.backup_engine import generate_backup_zip_stream

    stream = generate_backup_zip_stream(passphrase=passphrase(data_key))
    try:
        return stream.read()
    finally:
        stream.close()


def _named() -> str:
    from backend.services import host_basics
    from backend.services.identity import get_identity

    return get_identity().get("server_name") or host_basics.host_name()


def copy_if_due(now: float | None = None, force: bool = False) -> dict[str, str]:
    """Writes the copy to every pool that is due and awake. Says per pool: 'copied', 'waiting' (not
    due yet), 'asleep', or why it failed. `force` is the person asking for a copy now."""
    if not runtime.managed_host():
        return {}
    now = now or time.time()
    with _lock:
        state, out, made = _state(), {}, None
        for row in pools():
            name, last = row["name"], state.get(row["name"]) or {}
            if not force and last.get("at") and now - float(last["at"]) < EVERY:
                out[name] = "waiting"
                continue
            if asleep(row):
                out[name] = "asleep"
                continue
            try:
                if made is None:  # one archive for every pool of this round
                    data_key = machine_key.key_text()
                    with open(os.path.join(machine_key.DIR, machine_key.WRAPPED), "rb") as f:
                        wrapped = f.read()
                    from backend import __version__

                    about = {
                        "format": FORMAT,
                        "install": install_id(),
                        "name": _named(),
                        "version": __version__,
                        "at": now,
                    }
                    made = (_archive(data_key), wrapped, about)
                write_one(row, *made)
                state[name] = {"at": now, "error": ""}
                out[name] = "copied"
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("[PoolCopy] The settings were not copied to %s: %s", name, e)
                state[name] = {"at": float(last.get("at") or 0), "error": str(e)}
                out[name] = str(e)
        if out and any(v != "waiting" for v in out.values()):
            atomic_write_json(_state_file(), {k: v for k, v in state.items() if k in out})
    return out


def status() -> dict[str, Any]:
    """For the page: per pool when its copy was written, and whether the last try failed. No pool
    is touched to answer."""
    if not runtime.managed_host():
        return {"managed": False}
    state = _state()
    return {
        "managed": True,
        "locked": machine_key.status().get("locked", False),
        "found": found(),  # the settings of other installs that the last look turned up
        "pools": [
            {
                "name": row["name"],
                "at": float((state.get(row["name"]) or {}).get("at") or 0),
                "error": (state.get(row["name"]) or {}).get("error") or "",
            }
            for row in pools()
        ],
    }


# --- bringing the settings back from a copy --------------------------------------------------------
def _plain(text: Any, limit: int = 64) -> str:
    return "".join(ch for ch in str(text or "") if ch.isprintable())[:limit]


def _sets_in(root: str) -> list[tuple[str, dict[str, Any]]]:
    """The copies under a pool's root: its own and those set aside. [(folder, its note)]."""
    base = os.path.join(root, FOLDER)
    folders = [base]
    try:
        folders += [os.path.join(base, EARLIER, name) for name in sorted(os.listdir(os.path.join(base, EARLIER)))]
    except OSError:
        folders = [base]  # nothing was set aside here
    out = []
    for folder in folders:
        about = _about(folder)
        whole = all(os.path.isfile(os.path.join(folder, name)) for name in (ARCHIVE, WRAPPED))
        if about and whole and os.path.getsize(os.path.join(folder, ARCHIVE)) <= MAX_ARCHIVE:
            out.append((folder, about))
    return out


def _take(root: str, pool: str, mine: str) -> list[str]:
    """Copies every other install's settings copy found under `root` into FOUND; returns their keys."""
    keys = []
    for folder, about in _sets_in(root):
        theirs = "".join(ch for ch in str(about.get("install") or "") if ch.isalnum()).lower()[:16]
        if not theirs or theirs == mine:
            continue
        key = f"{theirs}-{''.join(ch for ch in pool.lower() if ch.isalnum())[:40] or 'pool'}"
        into = os.path.join(FOUND, key)
        shutil.rmtree(into, ignore_errors=True)
        os.makedirs(into, mode=0o700)
        for name in (ARCHIVE, WRAPPED):
            shutil.copyfile(os.path.join(folder, name), os.path.join(into, name))
            os.chmod(os.path.join(into, name), 0o600)
        note = {
            "key": key,
            "install": theirs,
            "name": _plain(about.get("name")) or "Kiboto",
            "version": _plain(about.get("version"), 24),
            "at": float(about.get("at") or 0),
            "pool": _plain(pool),
        }
        atomic_write_json(os.path.join(into, ABOUT), note)
        keys.append(key)
    return keys


def found() -> list[dict[str, Any]]:
    """The copies the last look turned up, newest first. No drive is touched."""
    out = []
    try:
        names = sorted(os.listdir(FOUND))
    except OSError:
        return []
    for name in names:
        note = _about(os.path.join(FOUND, name))
        if note.get("key") == name and _KEY.match(name):
            out.append(note)
    return sorted(out, key=lambda n: -float(n.get("at") or 0))


def look(run: Any = None) -> list[dict[str, Any]]:
    """Looks on every pool, in use or not, for the settings of another install. This reads the
    drives, so it wakes them: only ever at a person's request. Pools this system does not use are
    opened read-only and closed again (hardware/pal/pool_probe.py)."""
    if not runtime.managed_host():
        return []
    from backend.hardware.pal import pool_probe

    if run is None:
        from backend.hardware.pal_storage import get_storage_platform

        run = get_storage_platform()._run_cmd  # type: ignore[attr-defined]
    with _lock:
        shutil.rmtree(FOUND, ignore_errors=True)
        os.makedirs(FOUND, mode=0o700, exist_ok=True)
        mine = install_id()
        for row in pools():
            _take(row["mountpoint"], row["name"], mine)
        for candidate in pool_probe.candidates(run):
            try:
                pool_probe.look_into(candidate, run, lambda root, c=candidate: _take(root, c["name"], mine))
            except OSError as e:
                logger.warning("[PoolCopy] %s could not be looked into: %s", candidate["name"], e)
    return found()


def drop_index_after_restore(data_dir: str = "") -> bool:
    """At the start after settings were brought back from a pool copy: the AI search index of the
    install they replaced is encrypted under a key this machine no longer has. It is dropped, and
    Kiboto builds it again. Its files were not in the copy; the running Kiboto may have written to
    it until the restart, so this happens at the start, not at the restore."""
    data_dir = data_dir or DATA_DIR
    if not os.path.exists(os.path.join(data_dir, ADOPT_FLAG)):
        return False
    for end in ("", "-wal", "-shm"):
        path = os.path.join(data_dir, "rag_index.db" + end)
        if os.path.exists(path):
            os.remove(path)
    logger.info("[PoolCopy] The search index of the install before is dropped; it is built again")
    return True


def restore(key: str, typed_recovery_key: str) -> dict[str, Any]:
    """Brings back the settings of a found copy: opened with the recovery key of the install that
    wrote it, staged, and applied at the next start. That install's data key and recovery key
    become this machine's. Raises ValueError with a sentence for the person."""
    from backend import config, first_run
    from backend.services.backup_engine import restore_backup_archive

    folder = os.path.join(FOUND, key) if _KEY.match(key or "") else ""
    note = _about(folder) if folder else {}
    if not note:
        raise ValueError("That copy is no longer at hand. Look for it again.")
    recovery = machine_key.tidy(typed_recovery_key)
    box = read_json(os.path.join(folder, WRAPPED), None)
    if not recovery or not isinstance(box, dict):
        raise ValueError(machine_key.NOT_THE_KEY)
    try:
        data_key = machine_key.unwrap(box, recovery)
    except machine_key.MachineKeyError as e:
        raise ValueError(str(e)) from None
    from backend import db_crypto
    from backend.services.data_snapshot import take_snapshot

    try:  # today's settings first, under this machine's own key
        saved = take_snapshot(DATA_DIR, label="pre-restore", extra={"kind": "restore"})
    except (OSError, RuntimeError, ValueError) as e:
        raise ValueError(f"Could not save the current data before restoring: {e}") from e
    # the copy's AI databases are encrypted with its own data key, which becomes this machine's below
    with open(os.path.join(folder, ARCHIVE), "rb") as f, db_crypto.key_for_this_thread(data_key):
        result = restore_backup_archive(f, passphrase=passphrase(data_key), snapshot=False, staged=True)
    result["snapshot"] = saved
    machine_key.adopt(data_key, box)
    first_run.clear()  # the settings coming back have their own people and passwords
    if os.path.exists(config.initial_password_file()):
        os.remove(config.initial_password_file())
    with open(os.path.join(DATA_DIR, ADOPT_FLAG), "w", encoding="utf-8") as f:
        f.write(note.get("install", ""))
    logger.warning(
        "[PoolCopy] The settings of %s (from pool %s) are staged; they apply at the next start",
        note["name"],
        note["pool"],
    )
    return {"restored": result.get("restored"), "name": note["name"], "pool": note["pool"]}
