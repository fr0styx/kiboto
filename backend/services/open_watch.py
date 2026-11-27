"""Which files on the fast pool were opened, and on which day (data tiering, owner's decision 19 Nov 2026).

Most systems do not note when a file is opened (Unraid mounts every drive that way), and making
them note it costs a write per open. Kiboto listens instead: the kernel tells it about each open
on the fast pool's filesystem, and Kiboto keeps the day of the last one for the folders that have
tiering on, in a small record of its own. Nothing about the drives changes.

Opens by Kiboto itself (its search index, its backups) are left out: those are not a person using
the file. A program outside Kiboto that reads through a folder (a media scanner, an antivirus)
does count; the guide says so."""

import ctypes
import os
import select
import sqlite3
import struct
import threading
import time
from typing import Any

from backend.config import DATA_DIR, logger

DB_FILE = os.path.join(DATA_DIR, "tiering_opens.db")
FLUSH_SECS = 60.0
FAN_CLASS_NOTIF, FAN_CLOEXEC, FAN_NONBLOCK = 0x0, 0x1, 0x2
FAN_MARK_ADD, FAN_MARK_FILESYSTEM = 0x1, 0x100
FAN_OPEN = 0x20
AT_FDCWD = -100
EVENT = struct.Struct("IBBHQii")  # event_len, vers, reserved, metadata_len, mask, fd, pid

_lock = threading.Lock()
_seen: dict[str, int] = {}  # path -> day, not yet written
_state: dict[str, Any] = {"thread": None, "stop": None, "prefixes": (), "roots": (), "error": "", "listening": False}


def today(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // 86400)


# --- the record -----------------------------------------------------------------------------------
def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("CREATE TABLE IF NOT EXISTS opens (path TEXT PRIMARY KEY, day INTEGER NOT NULL) WITHOUT ROWID")
    conn.execute("CREATE TABLE IF NOT EXISTS kept (name TEXT PRIMARY KEY, value REAL NOT NULL) WITHOUT ROWID")
    conn.execute("CREATE TABLE IF NOT EXISTS watched (path TEXT PRIMARY KEY) WITHOUT ROWID")
    return conn


def mark_alive(now: float | None = None) -> None:
    """Notes that Kiboto was listening at this moment: a long stretch without it means opens were missed."""
    conn = _db()
    try:
        with conn:
            conn.execute(
                "INSERT INTO kept (name, value) VALUES ('alive', ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                (time.time() if now is None else now,),
            )
    finally:
        conn.close()


def mark_watched(folders: list[str]) -> None:
    """The service of the machine (Kiboto OS) notes the folders it listens on. The page and the
    mover read them: without them every merged folder counted as not watched, and nothing moved."""
    conn = _db()
    try:
        with conn:
            conn.execute("DELETE FROM watched")
            conn.executemany("INSERT OR IGNORE INTO watched (path) VALUES (?)", [(f.rstrip("/"),) for f in folders])
    finally:
        conn.close()


def watched_by_service() -> list[str]:
    conn = _db()
    try:
        return sorted(row[0] for row in conn.execute("SELECT path FROM watched"))
    finally:
        conn.close()


def last_alive() -> float | None:
    """When Kiboto was last known to be listening; None when it never has."""
    conn = _db()
    try:
        row = conn.execute("SELECT value FROM kept WHERE name = 'alive'").fetchone()
    finally:
        conn.close()
    return float(row[0]) if row else None


def note(path: str, day: int | None = None) -> None:
    """One open of a file. Kept in memory until the next flush."""
    with _lock:
        _seen[path] = today() if day is None else day


def flush() -> int:
    """Writes what was seen since the last time; returns how many files."""
    with _lock:
        batch = list(_seen.items())
        _seen.clear()
    if not batch:
        return 0
    conn = _db()
    try:
        with conn:
            conn.executemany(
                "INSERT INTO opens (path, day) VALUES (?, ?) ON CONFLICT(path) DO UPDATE SET day = MAX(day, excluded.day)",
                batch,
            )
    finally:
        conn.close()
    return len(batch)


def last_opened(folder: str) -> dict[str, int]:
    """path -> the day it was last seen opened, for every file under this folder that was."""
    flush()
    folder = folder.rstrip("/")
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT path, day FROM opens WHERE path >= ? AND path < ?", (folder + "/", folder + "0")
        ).fetchall()  # "0" is the character after "/": everything inside the folder
    finally:
        conn.close()
    return dict(rows)


def forget(folder: str) -> int:
    """Tiering was turned off for a folder, or its files moved: their opens are no longer kept."""
    flush()
    folder = folder.rstrip("/")
    conn = _db()
    try:
        with conn:
            return conn.execute("DELETE FROM opens WHERE path >= ? AND path < ?", (folder + "/", folder + "0")).rowcount
    finally:
        conn.close()


def forget_files(paths: list[str]) -> None:
    if not paths:
        return
    with _lock:
        for p in paths:
            _seen.pop(p, None)
    conn = _db()
    try:
        with conn:
            conn.executemany("DELETE FROM opens WHERE path = ?", [(p,) for p in paths])
    finally:
        conn.close()


# --- listening ------------------------------------------------------------------------------------
def wanted(path: str, prefixes: tuple[tuple[str, str], ...]) -> str | None:
    """The file's path as Kiboto knows it, when it is in a watched folder. An open made outside
    Kiboto's container arrives with the path the host knows the file by, which can differ."""
    for seen, known in prefixes:
        if path.startswith(seen):
            return known + path[len(seen) :]
    return None


def outside_kiboto(pid: int) -> bool:
    """On a machine of Kiboto's own every process is visible: an open counts unless the process is
    Kiboto's own user (its search index, its backups), which this listener runs as too."""
    try:
        with open(f"/proc/{pid}/status", encoding="ascii", errors="replace") as f:
            for line in f:
                if line.startswith("Uid:"):
                    return int(line.split()[1]) != os.getuid()
    except (OSError, ValueError, IndexError):
        return True  # gone already: someone opened it
    return True


def in_container(pid: int) -> bool:
    """In Kiboto's container: a process of its own has a number here; one outside shows as 0."""
    return pid == 0


def read_events(data: bytes, prefixes: tuple[tuple[str, str], ...], counts: Any = in_container) -> list[str]:
    """The files of the watched folders that these events say were opened by someone outside Kiboto.
    Each event carries an open handle to its file, which is closed here."""
    out = []
    off = 0
    while off + EVENT.size <= len(data):
        event_len, _vers, _reserved, _meta, _mask, fd, pid = EVENT.unpack_from(data, off)
        if event_len < EVENT.size:
            break
        off += event_len
        if fd < 0:
            continue
        try:
            if counts(pid):
                known = wanted(os.readlink(f"/proc/self/fd/{fd}"), prefixes)
                if known:
                    out.append(known)
        except OSError:
            continue
        finally:
            os.close(fd)
    return out


def _listen(
    stop: threading.Event, roots: tuple[str, ...], prefixes: tuple[tuple[str, str], ...], counts: Any = in_container
) -> None:
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.fanotify_mark.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_uint64, ctypes.c_int, ctypes.c_char_p]
    fd = libc.fanotify_init(FAN_CLASS_NOTIF | FAN_CLOEXEC | FAN_NONBLOCK, os.O_RDONLY | os.O_LARGEFILE)
    if fd < 0:
        _state["error"] = os.strerror(ctypes.get_errno())
        logger.warning("[Tiering] Kiboto cannot watch file opens on this system: %s", _state["error"])
        return
    try:
        for root in roots:
            if libc.fanotify_mark(fd, FAN_MARK_ADD | FAN_MARK_FILESYSTEM, FAN_OPEN, AT_FDCWD, root.encode()) != 0:
                _state["error"] = os.strerror(ctypes.get_errno())
                logger.warning("[Tiering] %s cannot be watched: %s", root, _state["error"])
                return
        _state["error"] = ""
        _state["listening"] = True
        flushed = time.time()
        _keep(False)
        while not stop.is_set():
            if select.select([fd], [], [], 1.0)[0]:
                try:
                    data = os.read(fd, 262144)
                except BlockingIOError:
                    data = b""
                day = today()
                for path in read_events(data, prefixes, counts):
                    note(path, day)
            if time.time() - flushed >= FLUSH_SECS:
                flushed = time.time()
                _keep(True)
    finally:
        os.close(fd)
        if _state.get("listening"):
            _keep(True)
        _state["listening"] = False


def _keep(with_opens: bool) -> None:
    try:
        if with_opens:
            flush()
        mark_alive()
    except sqlite3.Error:
        logger.warning("[Tiering] the record of opens could not be written", exc_info=True)


def watch(
    folders: list[str], roots: list[str], on_host: dict[str, str] | None = None, counts: Any = in_container
) -> None:
    """Listens for opens under `folders` (their paths on the fast pool); `roots` are the filesystems
    to listen on; `on_host` gives a folder's path as the host knows it, where that differs. Called
    again with other folders, it starts over. With none, it stops."""
    stop_watching()
    pairs = set()
    for f in folders:
        known = f.rstrip("/") + "/"
        pairs.add((known, known))
        outside = (on_host or {}).get(f)
        if outside:
            pairs.add((outside.rstrip("/") + "/", known))
    prefixes = tuple(sorted(pairs))
    if not prefixes or not roots:
        return
    stop = threading.Event()
    thread = threading.Thread(
        target=_listen, args=(stop, tuple(sorted(set(roots))), prefixes, counts), daemon=True, name="tiering-opens"
    )
    _state.update(thread=thread, stop=stop, prefixes=prefixes, roots=tuple(sorted(set(roots))), error="")
    thread.start()


def stop_watching() -> None:
    stop, thread = _state.get("stop"), _state.get("thread")
    if stop is not None:
        stop.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)
    _state.update(thread=None, stop=None, prefixes=(), roots=())


UNIT = "kiboto-open-watch"
ALIVE_SECS = 3 * FLUSH_SECS


def serve(folders: list[str]) -> int:
    """Kiboto OS: the listener as a service of the machine (started by the host door), until stopped."""
    import signal

    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    watch(folders, folders, counts=outside_kiboto)
    try:
        mark_watched(folders)
    except sqlite3.Error:
        logger.warning("[Tiering] the folders listened on could not be noted", exc_info=True)
    while not stopped.wait(5.0):
        thread = _state.get("thread")
        if thread is None or not thread.is_alive():
            return 1  # it could not listen: the unit starts it again
    stop_watching()
    return 0


def watch_here(folders: list[Any]) -> bool:
    """The host door's operation (ADR 0006): runs the listener as a service of the machine, as
    Kiboto's own user with only the rights to listen and to read the files it is told about
    (fanotify), over the given folders of the storage folder; none stops it."""
    from backend.config import POOL_PATH
    from backend.services.host_basics import run
    from backend.services.web_user import USER

    root = os.path.realpath(POOL_PATH).rstrip(os.sep) + os.sep
    if not isinstance(folders, list) or len(folders) > 64:
        raise ValueError("Not watching: too many folders.")
    checked = []
    for f in folders:
        real = os.path.realpath(f) if isinstance(f, str) and f.startswith("/") else ""
        if not real or real != os.path.normpath(f) or not real.startswith(root) or not os.path.isdir(real):
            raise ValueError("Not watching: that is not a folder in the storage folder.")
        checked.append(real)
    run(["systemctl", "stop", UNIT], timeout=30)
    run(["systemctl", "reset-failed", UNIT], timeout=30)
    if not checked:
        return True
    import sys

    caps = "CAP_SYS_ADMIN CAP_DAC_READ_SEARCH"
    release = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cmd = ["systemd-run", "--quiet", "--collect", "--unit", UNIT, "--description", "Kiboto: which files are opened"]
    cmd += ["--working-directory", release]  # where `python -m backend...` finds Kiboto's code
    cmd += ["-p", f"User={USER}", "-p", f"Group={USER}", "-p", f"AmbientCapabilities={caps}"]
    cmd += ["-p", f"CapabilityBoundingSet={caps}", "-p", "Restart=on-failure", "-p", "RestartSec=30"]
    cmd += ["--setenv", f"DATA_DIR={DATA_DIR}", sys.executable, "-m", "backend.services.open_watch", "serve", *checked]
    code, said = run(cmd, timeout=30)
    if code != 0:
        logger.warning("[Tiering] the listener for opens did not start: %s", said)
    return code == 0


def status() -> dict[str, Any]:
    from backend import runtime

    if runtime.without_root():  # a service of the machine: it marks itself alive every minute
        alive = last_alive()
        on = bool(alive and time.time() - alive < ALIVE_SECS)
        return {"watching": on, "folders": watched_by_service() if on else [], "error": ""}
    thread = _state.get("thread")
    return {
        "watching": bool(thread is not None and thread.is_alive() and _state.get("listening")),
        "folders": sorted({known.rstrip("/") for _seen_as, known in _state.get("prefixes") or ()}),
        "error": _state.get("error") or "",
    }


if __name__ == "__main__":
    import sys

    if sys.argv[1:2] != ["serve"]:
        print("usage: python -m backend.services.open_watch serve <folder>...", file=sys.stderr)
        sys.exit(2)
    sys.exit(serve(sys.argv[2:]))
