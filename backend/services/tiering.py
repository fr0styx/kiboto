"""Data tiering: files nobody opens move from the fast pool to the slow one (owner's decisions, 19 Nov 2026).

Per shared folder, off until turned on. The folder keeps showing every file in one place: on Unraid
that is the system's own merged folder (/mnt/user/<share> over the SSD pool and the array).

  - "Old" means not opened for N days (90 unless changed) and not changed in that time either.
    Kiboto watches opens itself (open_watch.py); no drive's mount is changed.
  - A folder is watched for N days before anything moves: until then Kiboto cannot know.
  - One way only: a file that moved stays on the slow pool.
  - Once a night, at RUN_AT. The move itself runs in a short-lived container that sees only the
    folder's two sides (tier_mover.py), and it wakes the slow pool's drives: that is the point.

On Unraid only a share that stays on the SSD pool fits (cache "only"): Unraid's own mover empties a
"yes" share to the array every night and brings a "prefer" share's files back."""

import os
import shutil
import socket
import sqlite3
import threading
import time
import uuid
from typing import Any

from backend import legacy_names, product
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json
from backend.services import open_watch

STATE_FILE = os.path.join(DATA_DIR, "tiering.json")
JOBS_DIR = os.path.join(DATA_DIR, "tiering")
CONTAINER = "kiboto-mover"
MOVER = "/app/backend/services/tier_mover.py"
DEFAULT_DAYS = 90
MIN_DAYS, MAX_DAYS = 7, 3650
RUN_AT = "03:00"
MAX_FILES_PER_RUN = 20000
RUN_LIMIT_SECS = 6 * 3600
MAX_UNWATCHED_SECS = 3600  # longer than this without listening, and Kiboto no longer knows what was opened
RETRY_WATCH_SECS = 600
SETTLE_SECS = 2.0  # for the watcher to have read the mover's last opens
STOP_WAIT_SECS = 60  # the mover ends cleanly when asked; a file in hand stays where it was
MNT = "/mnt"
UNRAID_SLOW = "/mnt/user0"  # the array alone, on the host
# what the mover may do as root, and nothing else: read and write other people's files, keep their
# owner and mode, and ask whether a file is open (LEASE)
MOVER_MAY = ["CHOWN", "DAC_OVERRIDE", "DAC_READ_SEARCH", "FOWNER", "FSETID", "LEASE"]
ELEVATED = {"X-Kiboto-Elevated": "1"}

_lock = threading.Lock()
_ran: dict[str, str] = {}  # folder id -> the day it last ran on its schedule
_busy: set[str] = set()
_tried = {"watch": 0.0}


class NotNow(RuntimeError):
    """Something that cannot be done; `key` names the sentence for the screen."""

    def __init__(self, key: str, message: str, **params: Any):
        super().__init__(message)
        self.key = key
        self.params = params


# --- what is kept -------------------------------------------------------------------------------
def _read() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    data = data if isinstance(data, dict) else {}
    return {"folders": [f for f in data.get("folders") or [] if isinstance(f, dict) and f.get("id") and f.get("name")]}


def folders() -> list[dict[str, Any]]:
    return _read()["folders"]


def get(name: str) -> dict[str, Any] | None:
    return next((f for f in folders() if f["name"] == name), None)


# --- which shared folders fit ---------------------------------------------------------------------
def candidates() -> list[dict[str, Any]]:
    """Each shared folder with its two sides, or why tiering does not fit it (`why`)."""
    from backend.hardware.pal.base import PlatformType
    from backend.hardware.pal_storage import get_storage_platform

    try:
        plat = get_storage_platform()
        kind, shares = plat.get_platform_type(), list(plat.list_shares())
    except (OSError, RuntimeError, ValueError):
        logger.debug("[Tiering] the shared folders could not be read", exc_info=True)
        return []
    out = []
    for s in shares:
        entry: dict[str, Any] = {"name": s.name, "why": "", "fast": "", "merged": "", "slow_host": ""}
        if kind != PlatformType.UNRAID:
            entry["why"] = "no_merged_folder"  # Kiboto's own pools: see merged folders
        elif s.cache_mode == "yes":
            entry["why"] = "unraid_moves_all"
        elif s.cache_mode == "prefer":
            entry["why"] = "unraid_moves_back"
        elif s.cache_mode != "only" or not s.cache_pool:
            entry["why"] = "not_on_fast"
        else:
            fast = os.path.join(MNT, s.cache_pool, s.name)
            merged = s.mountpoint or os.path.join(MNT, "user", s.name)
            if os.path.islink(merged):
                entry["why"] = "exclusive"  # Unraid points the folder straight at the pool: the array would not show
            elif not os.path.isdir(fast):
                entry["why"] = "fast_not_visible"
            else:
                entry.update(fast=fast, merged=merged, slow_host=os.path.join(UNRAID_SLOW, s.name))
        out.append(entry)
    return out


# --- turning it on and off ------------------------------------------------------------------------
@json_locked(lambda *a, **k: STATE_FILE)
def set_folder(name: str, enabled: bool, days: int = DEFAULT_DAYS, now: float | None = None) -> dict[str, Any] | None:
    """Turns tiering on for a shared folder (watching starts now), changes its days, or turns it off
    (its record of opens is forgotten). NotNow when the folder does not fit."""
    data = _read()
    old = next((f for f in data["folders"] if f["name"] == name), None)
    if not enabled:
        if old is not None:
            data["folders"] = [f for f in data["folders"] if f["name"] != name]
            atomic_write_json(STATE_FILE, data)
            open_watch.forget(old["fast"])
        return None
    if not isinstance(days, int) or isinstance(days, bool) or not MIN_DAYS <= days <= MAX_DAYS:
        raise NotNow("bad_days", f"The number of days must be between {MIN_DAYS} and {MAX_DAYS}.", value=MAX_DAYS)
    fit = next((c for c in candidates() if c["name"] == name), None)
    if fit is None:
        raise NotNow("no_folder", "There is no such shared folder.")
    if fit["why"]:
        raise NotNow("no_fit", "Tiering does not fit this shared folder.")
    if old is not None:
        old.update(days=days, fast=fit["fast"], merged=fit["merged"], slow_host=fit["slow_host"])
        fresh = old
    else:
        fresh = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "fast": fit["fast"],
            "merged": fit["merged"],
            "slow_host": fit["slow_host"],
            "days": days,
            "since": time.time() if now is None else now,  # nothing is known about opens before this
            "last_run": None,
        }
        data["folders"].append(fresh)
    atomic_write_json(STATE_FILE, data)
    return fresh


@json_locked(lambda *a, **k: STATE_FILE)
def _note_run(folder_id: str, run: dict[str, Any]) -> None:
    data = _read()
    for f in data["folders"]:
        if f["id"] == folder_id:
            f["last_run"] = run
    atomic_write_json(STATE_FILE, data)


# --- which files are old --------------------------------------------------------------------------
def learning_until(folder: dict[str, Any]) -> float:
    """When Kiboto has watched this folder long enough to say a file was not opened."""
    return float(folder["since"]) + folder["days"] * 86400


def select(folder: dict[str, Any], now: float | None = None, limit: int = MAX_FILES_PER_RUN) -> dict[str, Any]:
    """The files on the fast side to move tonight: not opened and not changed for the folder's days.
    Nothing while Kiboto is still learning. Walks the fast pool only, which wakes no drive."""
    now = time.time() if now is None else now
    out: dict[str, Any] = {"files": [], "bytes": 0, "learning": now < learning_until(folder), "more": False, "why": ""}
    if out["learning"]:
        return out
    fast = folder["fast"].rstrip("/")
    watched = open_watch.status()
    if not watched["watching"] or fast not in watched["folders"]:
        out["why"] = "not_watching"  # without the record of opens every file would look unused
        return out
    opened = open_watch.last_opened(fast)
    old_before = now - folder["days"] * 86400
    old_day = open_watch.today(now) - folder["days"]
    for root, dirs, names in os.walk(fast):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not os.path.islink(os.path.join(root, d)))
        for name in sorted(names):
            path = os.path.join(root, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if not os.path.isfile(path) or os.path.islink(path) or st.st_nlink > 1 or name.startswith("."):
                continue
            if max(st.st_mtime, st.st_ctime) > old_before or opened.get(path, -1) > old_day:
                continue
            if len(out["files"]) >= limit:
                out["more"] = True
                return out
            out["files"].append(path[len(fast) + 1 :])
            out["bytes"] += st.st_size
    return out


# --- the move, in a container of its own ----------------------------------------------------------
def _docker(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, Any]:
    from backend.services.container_mutator import docker_request

    try:
        return docker_request(method, path, body=body, headers=headers)
    except (OSError, RuntimeError):
        logger.debug("[Tiering] Docker did not answer %s %s", method, path, exc_info=True)
        return 0, None


def _self() -> dict[str, Any]:
    for ref in (socket.gethostname(), *legacy_names.app_container_names()[:2]):
        code, info = _docker("GET", f"/containers/{ref}/json")
        if code == 200 and isinstance(info, dict):
            return info
    return {}


def desired(me: dict[str, Any], folder: dict[str, Any], job_dir: str) -> dict[str, Any] | None:
    """The mover's container: Kiboto's image, the folder's two sides and the job, no network."""
    from backend.services.iscsi_target import host_path

    fast, job = host_path(me, folder["fast"]), host_path(me, job_dir)
    if fast is None or job is None:
        return None
    return {
        "Image": (me.get("Config") or {}).get("Image") or product.IMAGE + ":latest",
        "Entrypoint": ["python3"],
        "Cmd": [MOVER, "/job/job.json"],
        "Healthcheck": {"Test": ["NONE"]},
        "Labels": {"app": CONTAINER, "managed-by": product.CONTAINER},
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "CapAdd": MOVER_MAY,
            "Binds": [f"{fast}:/fast", f"{folder['slow_host']}:/slow", f"{job}:/job"],
        },
    }


def _wait(seconds: float) -> bool:
    """True when the mover's container has ended within the time."""
    end = time.time() + seconds
    while time.time() < end:
        code, info = _docker("GET", f"/containers/{CONTAINER}/json")
        if code != 200 or not ((info or {}).get("State") or {}).get("Running"):
            return True
        time.sleep(2)
    return False


def _mover_at_work() -> bool:
    """A mover started before Kiboto restarted may still be moving files."""
    code, info = _docker("GET", f"/containers/{CONTAINER}/json")
    return code == 200 and bool(((info or {}).get("State") or {}).get("Running"))


def _claim(name: str) -> dict[str, Any]:
    folder = get(name)
    if folder is None:
        raise NotNow("no_folder", "Tiering is not on for this shared folder.")
    with _lock:
        if _busy:
            raise NotNow("busy", "Files are being moved already. Try again when that has finished.")
        _busy.add(folder["id"])
    if _mover_at_work():
        with _lock:
            _busy.discard(folder["id"])
        raise NotNow("busy", "Files are being moved already. Try again when that has finished.")
    return folder


def run(name: str, how: str = "schedule", now: float | None = None) -> dict[str, Any]:
    """One run for a folder: choose, move, record. Returns the run. NotNow when it cannot start."""
    folder = _claim(name)
    try:
        return _run(folder, how, now)
    finally:
        with _lock:
            _busy.discard(folder["id"])


def run_soon(name: str, how: str = "hand") -> None:
    """Starts a run and returns at once (the screen's button). NotNow when it cannot start."""
    folder = _claim(name)

    def work() -> None:
        try:
            _run(folder, how, None)
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("[Tiering] the run for %s failed", folder["name"], exc_info=True)
        finally:
            with _lock:
                _busy.discard(folder["id"])

    threading.Thread(target=work, name="tiering-run", daemon=True).start()


def _hand_to_mover(folder: dict[str, Any], job_dir: str, files: list[str]) -> str:
    """Writes the job and runs the mover's container until it ends. Returns why it could not, or ""."""
    os.makedirs(job_dir, mode=0o700, exist_ok=True)
    for leftover in ("job.json", "result.json"):
        if os.path.exists(os.path.join(job_dir, leftover)):
            os.remove(os.path.join(job_dir, leftover))
    atomic_write_json(os.path.join(job_dir, "job.json"), {"fast": "/fast", "slow": "/slow", "files": files})
    me = _self()
    want = desired(me, folder, job_dir) if me else None
    if want is None:
        return "no_engine" if not me else "no_path"
    why = ""
    _docker("DELETE", f"/containers/{CONTAINER}?force=true")
    created, _resp = _docker("POST", f"/containers/create?name={CONTAINER}", want, ELEVATED)
    started, _ = _docker("POST", f"/containers/{CONTAINER}/start") if created in (200, 201) else (0, None)
    if started not in (200, 204, 304):
        why = "no_start"
    elif not _wait(RUN_LIMIT_SECS):
        why = "too_long"
        _docker("POST", f"/containers/{CONTAINER}/stop?t={STOP_WAIT_SECS}")
    _docker("DELETE", f"/containers/{CONTAINER}?force=true")
    return why


def _run(folder: dict[str, Any], how: str, now: float | None) -> dict[str, Any]:
    started = time.time()
    chosen = select(folder, now)
    result: dict[str, Any] = {"started": started, "how": how, "learning": chosen["learning"], "more": chosen["more"]}
    result.update(chosen=len(chosen["files"]), moved=0, bytes=0, counts={}, errors=[], why=chosen["why"])
    if chosen["files"]:
        job_dir = os.path.join(JOBS_DIR, folder["id"])
        result["why"] = _hand_to_mover(folder, job_dir, chosen["files"])
        if result["why"] not in ("no_engine", "no_path"):
            done = read_json(os.path.join(job_dir, "result.json"), None)
            if isinstance(done, dict):
                moved = [str(m) for m in done.get("moved") or []]
                result.update(moved=len(moved), bytes=int(done.get("bytes") or 0), counts=done.get("counts") or {})
                result["errors"] = list(done.get("errors") or [])[:20]
                if done.get("stopped") == "full" and not result["why"]:
                    result["why"] = "full"
            elif not result["why"]:
                result["why"] = "no_result"
            # the mover looked at each file, which the watcher saw as an open: that is not a person
            # using it, and a file that stayed must not count as opened today
            time.sleep(SETTLE_SECS)
            open_watch.forget_files([os.path.join(folder["fast"], rel) for rel in chosen["files"]])
        shutil.rmtree(job_dir, ignore_errors=True)
    result["ended"] = time.time()
    _note_run(folder["id"], result)
    _tell(folder, result)
    return result


def _tell(folder: dict[str, Any], run_: dict[str, Any]) -> None:
    """A run that moved something, or could not, goes to the activity log."""
    from backend.state import add_event, event_text

    if run_["why"] or run_["errors"]:
        add_event(
            "warning",
            "Data tiering",
            f"Old files of {folder['name']} could not all be moved ({run_['why'] or 'errors'}).",
            event_text("tiering_problem", name=folder["name"], moved=run_["moved"]),
        )
    elif run_["moved"]:
        add_event(
            "info",
            "Data tiering",
            f"{run_['moved']} old files of {folder['name']} moved to the slower drives ({run_['bytes']} bytes).",
            event_text("tiering_done", name=folder["name"], count=run_["moved"]),
        )


# --- the timer and the watcher --------------------------------------------------------------------
def run_due(now: float | None = None) -> list[str]:
    """Called every minute by the scheduler: at RUN_AT, once a day, each folder that is on."""
    now = time.time() if now is None else now
    if now - _tried["watch"] >= RETRY_WATCH_SECS and folders() and not open_watch.status()["watching"]:
        _tried["watch"] = now
        watch_soon()  # the listener ended, or could not start: try again
    t = time.localtime(now)
    if f"{t.tm_hour:02d}:{t.tm_min:02d}" != RUN_AT:
        return []
    day = time.strftime("%Y-%m-%d", t)
    due = []
    for folder in folders():
        if _ran.get(folder["id"]) != day:
            _ran[folder["id"]] = day
            due.append(folder["name"])
    if due:
        threading.Thread(target=_run_all, args=(due, now), name="tiering-night", daemon=True).start()
    return due


def _run_all(names: list[str], now: float) -> None:
    """The night's runs, one folder after the other (a run can take hours)."""
    for name in names:
        try:
            run(name, "schedule", now if len(names) == 1 else None)
        except NotNow as e:
            logger.warning("[Tiering] %s was due and did not run: %s", name, e)
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("[Tiering] the run for %s failed", name, exc_info=True)


def _booted() -> float:
    """When the system started (0 when it cannot be read): while it was off, nobody opened a file."""
    try:
        with open("/proc/stat", encoding="ascii") as f:
            for line in f:
                if line.startswith("btime "):
                    return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def unwatched_secs(now: float | None = None) -> float:
    """How long the system ran without Kiboto listening for opens, up to now."""
    now = time.time() if now is None else now
    alive = open_watch.last_alive()
    return 0.0 if alive is None else max(0.0, now - max(alive, _booted()))


@json_locked(lambda *a, **k: STATE_FILE)
def _learn_again(now: float) -> list[str]:
    data = _read()
    for f in data["folders"]:
        f["since"] = now
    atomic_write_json(STATE_FILE, data)
    return [f["name"] for f in data["folders"]]


def watch(now: float | None = None) -> None:
    """Listens for opens in the folders that have tiering on (at start, and after a change). After
    a long stretch without listening, what was opened meanwhile is unknown: the folders are watched
    for their full time again before anything moves."""
    from backend.services.iscsi_target import host_path
    from backend.state import add_event, event_text

    now = time.time() if now is None else now
    if not folders():
        open_watch.watch([], [])  # tiering is off everywhere: nothing listens, no record is kept
        return
    missed = unwatched_secs(now)
    if missed > MAX_UNWATCHED_SECS:
        names = _learn_again(now)
        add_event(
            "warning",
            "Data tiering",
            f"Kiboto did not see which files were opened for {int(missed // 3600)} hours, so it watches "
            f"{', '.join(names)} for the full time again before it moves anything.",
            event_text("tiering_relearn", hours=int(missed // 3600)),
        )
    kept = folders()
    me = _self() if kept else {}
    fast = [f["fast"] for f in kept if os.path.isdir(f["fast"])]
    on_host = {p: h for p in fast if (h := host_path(me, p)) and h != p}
    open_watch.watch(fast, fast, on_host)


def watch_soon() -> None:
    def start() -> None:
        try:
            watch()
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            logger.warning("[Tiering] Could not start watching file opens", exc_info=True)

    threading.Thread(target=start, name="tiering-watch", daemon=True).start()


def view(now: float | None = None) -> dict[str, Any]:
    """What the screen shows: each shared folder, whether tiering fits or is on, and how it stands."""
    now = time.time() if now is None else now
    kept = {f["name"]: f for f in folders()}
    out = []
    for c in candidates():
        on = kept.get(c["name"])
        entry: dict[str, Any] = {"name": c["name"], "why": c["why"], "enabled": on is not None}
        if on is not None:
            entry.update(
                days=on["days"], since=on["since"], learning_until=learning_until(on), last_run=on.get("last_run")
            )
            entry["learning"] = now < entry["learning_until"]
        out.append(entry)
    with _lock:
        busy = bool(_busy)
    watched = open_watch.status()
    for entry in out:
        if entry["enabled"]:
            entry["watching"] = watched["watching"] and kept[entry["name"]]["fast"].rstrip("/") in watched["folders"]
    return {
        "folders": out,
        "run_at": RUN_AT,
        "default_days": DEFAULT_DAYS,
        "min_days": MIN_DAYS,
        "max_days": MAX_DAYS,
        "moving": busy,
        "watch_error": watched["error"],
    }
