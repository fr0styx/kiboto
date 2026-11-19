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


def read_events(data: bytes, prefixes: tuple[tuple[str, str], ...]) -> list[str]:
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
            # a process of Kiboto's own has a number here; one outside its container shows as 0
            if pid == 0:
                known = wanted(os.readlink(f"/proc/self/fd/{fd}"), prefixes)
                if known:
                    out.append(known)
        except OSError:
            continue
        finally:
            os.close(fd)
    return out


def _listen(stop: threading.Event, roots: tuple[str, ...], prefixes: tuple[tuple[str, str], ...]) -> None:
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
                for path in read_events(data, prefixes):
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


def watch(folders: list[str], roots: list[str], on_host: dict[str, str] | None = None) -> None:
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
        target=_listen, args=(stop, tuple(sorted(set(roots))), prefixes), daemon=True, name="tiering-opens"
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


def status() -> dict[str, Any]:
    thread = _state.get("thread")
    return {
        "watching": bool(thread is not None and thread.is_alive() and _state.get("listening")),
        "folders": sorted({known.rstrip("/") for _seen_as, known in _state.get("prefixes") or ()}),
        "error": _state.get("error") or "",
    }
