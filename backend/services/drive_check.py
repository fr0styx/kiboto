"""A check for a new drive, before it is trusted with data (owner's decision, 19 Nov 2026).

It reads the drive's whole surface from this side (so the cable and the controller are tried too,
which the drive's own self-test does not do), notes how fast each part read and what could not be
read, and compares the drive's own counters from before with after. It only ever reads. It is
started by hand, never by Kiboto, and only on a drive that is not in a pool, not mounted and not
the system's own: hours of reading would slow a drive that is in use, and a new drive is the one
this is for. It stops by itself if the drive gets too hot, and it can be stopped at any time."""

import errno
import mmap
import os
import re
import threading
import time
from typing import Any

from backend.config import DATA_DIR, HDD_CRITICAL_TEMP, HOST_PROC, HOST_SYS, NVME_CRITICAL_TEMP, OS_NVME, logger
from backend.fsutil import atomic_write_json, json_locked, read_json
from backend.state import Z_STATE

RESULTS_FILE = os.path.join(DATA_DIR, "drive_checks.json")
DEV_DIR = "/dev"
CHUNK = 4 * 1024 * 1024  # read in pieces of this size; one that cannot be read is counted and skipped
MAX_AT_ONCE = 2
RESULTS_KEPT = 5  # per drive
BAD_PLACES_LISTED = 50
HEAT_MARGIN_C = 3  # stop this many degrees before the temperature Kiboto calls critical
SPEED_WINDOW_SECS = 5.0
VALID_DEV = re.compile(r"^(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)$")
WATCHED = ("realloc", "pending", "offline", "crc", "nvme_media_err")  # the counters compared before and after

_LOCK = threading.Lock()
_ACTIVE: dict[str, dict[str, Any]] = {}


class NotNow(RuntimeError):
    """A check that cannot start; `key` names the sentence for the screen."""

    def __init__(self, key: str, message: str):
        super().__init__(message)
        self.key = key


# --- which drives may be checked ------------------------------------------------------------------
def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def size_bytes(dev: str) -> int:
    sectors = _read(os.path.join(HOST_SYS, "block", dev, "size")).strip()
    return int(sectors) * 512 if sectors.isdigit() else 0


def _parts(dev: str) -> list[str]:
    """The drive and its partitions, as the kernel names them (sdb, sdb1; nvme0n1, nvme0n1p1)."""
    try:
        inside = os.listdir(os.path.join(HOST_SYS, "block", dev))
    except OSError:
        inside = []
    return [dev, *sorted(n for n in inside if n.startswith(dev))]


def drives() -> list[dict[str, Any]]:
    """The drives Kiboto shows (from its live record), or what the kernel lists before the first reading."""
    stats = Z_STATE.cached_stats if isinstance(Z_STATE.cached_stats, dict) else {}
    known = [d for d in stats.get("disks") or [] if isinstance(d, dict) and VALID_DEV.match(str(d.get("dev") or ""))]
    if known:
        return [{"dev": d["dev"], "role": d.get("role") or ""} for d in known]
    try:
        names = sorted(os.listdir(os.path.join(HOST_SYS, "block")))
    except OSError:
        names = []
    return [{"dev": n, "role": "os" if n == OS_NVME else ""} for n in names if VALID_DEV.match(n)]


def _mounted() -> set[str]:
    """The devices something is mounted from, as the system itself sees them (not only this container)."""
    seen: set[str] = set()
    for table in (os.path.join(HOST_PROC, "1", "mounts"), os.path.join(HOST_PROC, "mounts")):
        seen |= {line.split(" ", 1)[0].removeprefix("/dev/") for line in _read(table).splitlines()}
    return seen


def in_use(dev: str) -> str | None:
    """Why this drive is not one to check ("os", "pool", "mounted", "held"), or None when it is free.
    Read from the kernel's tables and the pool list Kiboto already keeps: no drive is woken."""
    if any(d["dev"] == dev and d["role"] == "os" for d in drives()):
        return "os"
    parts = _parts(dev)
    try:
        from backend.hardware.pal_storage import get_storage_platform

        for pool in get_storage_platform().list_pools():
            for member in getattr(pool, "members", None) or []:
                if str(getattr(member, "device", "")).removeprefix("/dev/") in parts:
                    return "pool"
    except (OSError, RuntimeError, ValueError):
        logger.debug("[DriveCheck] the pools could not be read", exc_info=True)
        return "pool"  # not known to be free: not offered
    if _mounted() & set(parts):
        return "mounted"
    for part in parts:
        base = os.path.join(HOST_SYS, "block", dev) if part == dev else os.path.join(HOST_SYS, "block", dev, part)
        try:
            if os.listdir(os.path.join(base, "holders")):
                return "held"  # part of an array, an encrypted volume or a volume group
        except OSError:
            continue
    return None


def candidates() -> list[dict[str, Any]]:
    """Every drive, with whether it may be checked and if not, why."""
    out = []
    for d in drives():
        dev = d["dev"]
        why = in_use(dev)
        out.append({"dev": dev, "size_bytes": size_bytes(dev), "free": why is None, "in_use": why})
    return out


# --- the drive's own counters ---------------------------------------------------------------------
def counters(dev: str) -> dict[str, Any]:
    """The drive's own counters that matter here, read now (the drive is awake: it is being read)."""
    from backend.hardware.disks import read_smart_detail

    try:
        detail = read_smart_detail(dev, True)
    except (OSError, RuntimeError, ValueError):
        logger.debug("[DriveCheck] no SMART reading for %s", dev, exc_info=True)
        return {}
    metrics = detail.get("metrics") if isinstance(detail, dict) else None
    metrics = metrics if isinstance(metrics, dict) else {}
    found: dict[str, Any] = {k: metrics.get(k) for k in WATCHED if isinstance(metrics.get(k), (int, float))}
    found["serial"] = str(detail.get("serial") or metrics.get("serial") or "") if isinstance(detail, dict) else ""
    found["model"] = str(detail.get("model") or "") if isinstance(detail, dict) else ""
    return found


def _temperature(dev: str) -> float | None:
    with Z_STATE.lock:
        seen = (Z_STATE.cached_smart_data or {}).get(dev)
    temp = seen[0] if isinstance(seen, (tuple, list)) and seen else None
    return float(temp) if isinstance(temp, (int, float)) and not isinstance(temp, bool) else None


def heat_limit(dev: str) -> float:
    return float(NVME_CRITICAL_TEMP if dev.startswith("nvme") else HDD_CRITICAL_TEMP) - HEAT_MARGIN_C


# --- the verdict ----------------------------------------------------------------------------------
def verdict(run: dict[str, Any]) -> str:
    """good, bad (do not trust it), cable (the counters point at the connection), or unfinished."""
    if run["state"] != "finished":
        return "unfinished"
    before, after = run.get("before") or {}, run.get("after") or {}
    grew = {k: after[k] - before[k] for k in WATCHED if k in before and k in after and after[k] > before[k]}
    if run["unreadable"] or any(k in grew for k in ("realloc", "pending", "offline", "nvme_media_err")):
        return "bad"
    return "cable" if "crc" in grew else "good"


# --- the record -----------------------------------------------------------------------------------
def results() -> dict[str, list[dict[str, Any]]]:
    data = read_json(RESULTS_FILE, {})
    return (
        {k: [r for r in v if isinstance(r, dict)] for k, v in data.items() if isinstance(v, list)}
        if isinstance(data, dict)
        else {}
    )


@json_locked(lambda *a, **k: RESULTS_FILE)
def _keep(key: str, run: dict[str, Any]) -> None:
    data = results()
    data[key] = [run, *data.get(key, [])][:RESULTS_KEPT]
    atomic_write_json(RESULTS_FILE, data)


def _public(run: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in run.items() if k not in ("stop", "thread")}


def active() -> dict[str, dict[str, Any]]:
    with _LOCK:
        return {dev: _public(run) for dev, run in _ACTIVE.items()}


# --- the reading ----------------------------------------------------------------------------------
def start(dev: str, who: str = "") -> dict[str, Any]:
    """Starts the check in the background. Raises NotNow: no such drive, in use, running, or too many."""
    if not VALID_DEV.match(dev) or size_bytes(dev) <= 0 or not os.path.exists(os.path.join(DEV_DIR, dev)):
        raise NotNow("no_drive", "There is no such drive.")
    why = in_use(dev)
    if why:
        raise NotNow(f"in_use_{why}", "This drive is in use, so it is not checked this way.")
    with _LOCK:
        if dev in _ACTIVE:
            raise NotNow("running", "This drive is already being checked.")
        if len(_ACTIVE) >= MAX_AT_ONCE:
            raise NotNow("busy", "Two drives are being checked already. Start this one when one has finished.")
        run: dict[str, Any] = {
            "dev": dev,
            "who": who,
            "state": "running",
            "started": time.time(),
            "ended": None,
            "size_bytes": size_bytes(dev),
            "read_bytes": 0,
            "speed_bps": 0.0,
            "slowest_bps": None,
            "eta_secs": None,
            "unreadable": 0,
            "bad_places": [],
            "why": "",
            "stop": threading.Event(),
        }
        _ACTIVE[dev] = run
    threading.Thread(target=_check, args=(run,), daemon=True, name=f"drive-check-{dev}").start()
    return _public(run)


def stop(dev: str) -> bool:
    with _LOCK:
        run = _ACTIVE.get(dev)
    if run is None:
        return False
    run["stop"].set()
    return True


def _read_surface(run: dict[str, Any], path: str) -> None:
    """Reads the drive from start to end past the page cache, so every piece really comes off it."""
    dev, size = run["dev"], run["size_bytes"]
    limit = heat_limit(dev)
    buf = mmap.mmap(-1, CHUNK)  # page-aligned, as reading past the cache needs
    fd, direct = _open(path)
    try:
        offset, mark_at, mark_bytes = 0, time.time(), 0
        while offset < size:
            if run["stop"].is_set():
                run["state"] = "stopped"
                return
            want = min(CHUNK, size - offset)
            try:
                got = min(want, os.preadv(fd, [buf], offset))
            except OSError as e:
                if e.errno == errno.EINVAL and direct and offset == 0:
                    os.close(fd)  # this kind of storage cannot be read past the cache: read it plainly
                    fd, direct = os.open(path, os.O_RDONLY), False
                    continue
                if e.errno not in (errno.EIO, errno.ENODATA, errno.EILSEQ, errno.EBADMSG, errno.EREMOTEIO):
                    raise  # the drive is gone or cannot be read at all: that is the result
                run["unreadable"] += 1
                if len(run["bad_places"]) < BAD_PLACES_LISTED:
                    run["bad_places"].append(offset)
                got = want  # counted, and on to the next piece
            if got <= 0:
                break
            if not direct:  # what was read does not stay in memory in place of something useful
                os.posix_fadvise(fd, offset, got, os.POSIX_FADV_DONTNEED)
            offset += got
            run["read_bytes"] = offset
            now = time.time()
            if now - mark_at >= SPEED_WINDOW_SECS:
                speed = (offset - mark_bytes) / (now - mark_at)
                run["speed_bps"] = speed
                run["slowest_bps"] = speed if run["slowest_bps"] is None else min(run["slowest_bps"], speed)
                run["eta_secs"] = (size - offset) / speed if speed > 0 else None
                mark_at, mark_bytes = now, offset
                temp = _temperature(dev)
                if temp is not None and temp >= limit:
                    run["state"], run["why"] = "too_hot", f"{temp:.0f}"
                    return
        run["state"] = "finished"
    finally:
        os.close(fd)
        buf.close()


def _open(path: str) -> tuple[int, bool]:
    """The drive opened for reading past the page cache where that is possible; (fd, past the cache?)."""
    try:
        return os.open(path, os.O_RDONLY | os.O_DIRECT), True
    except OSError as e:
        if e.errno != errno.EINVAL:
            raise
        return os.open(path, os.O_RDONLY), False


def _check(run: dict[str, Any]) -> None:
    dev = run["dev"]
    try:
        run["before"] = counters(dev)
        _read_surface(run, os.path.join(DEV_DIR, dev))
    except OSError as e:
        run["state"], run["why"] = "failed", e.strerror or str(e)
        logger.warning("[DriveCheck] %s could not be read: %s", dev, e)
    run["after"] = counters(dev) if run["state"] != "failed" else {}
    run["ended"] = time.time()
    run["eta_secs"] = None
    run["verdict"] = verdict(run)
    try:
        record = _public(run)
        _keep(str((run.get("before") or {}).get("serial") or dev), record)
        _tell(record)
    finally:
        with _LOCK:
            _ACTIVE.pop(dev, None)


def _tell(run: dict[str, Any]) -> None:
    """The end of a check goes to the activity log; a drive not to be trusted is a warning."""
    from backend.state import add_event, event_text

    name = f"drive_check_{run['verdict'] if run['state'] == 'finished' else run['state']}"
    level = "warning" if run["verdict"] in ("bad", "cable") or run["state"] in ("failed", "too_hot") else "info"
    add_event(
        level,
        "Drive check",
        f"The check of {run['dev']} ended: {run['verdict']} ({run['state']}, {run['unreadable']} unreadable places).",
        event_text(name, dev=run["dev"], count=run["unreadable"], why=run["why"]),
    )


def view() -> dict[str, Any]:
    """What the screen shows: the drives, the checks that are going, and each drive's last result."""
    kept = results()
    going = active()
    drives = []
    for c in candidates():
        last = None
        for runs in kept.values():
            mine = [r for r in runs if r.get("dev") == c["dev"]]
            if mine and (last is None or mine[0].get("ended", 0) > last.get("ended", 0)):
                last = mine[0]
        drives.append({**c, "check": going.get(c["dev"]), "last": last})
    return {"drives": drives, "max_at_once": MAX_AT_ONCE}


def reset_for_tests() -> None:
    with _LOCK:
        for run in _ACTIVE.values():
            run["stop"].set()
        _ACTIVE.clear()
