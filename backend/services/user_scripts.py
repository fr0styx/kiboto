"""An administrator's own scripts, run on a timer (owner's decision, 19 Nov 2026).

Off until an administrator turns it on. A script runs inside Kiboto with Kiboto's rights: it can
read and change every file Kiboto can. A script may instead be limited to one folder: then it
runs in a view of the system where only that folder (and a scratch /tmp) can be written, where
Kiboto's own data, the drives themselves and the apps' control socket are not there, and from
which it cannot get the rights back (see LIMIT_WRAP). Every run is written to the security log,
with who or what started it and how it ended; the end of its output is kept for reading.

A run that was due while the NAS was off is not caught up: a script meant for the night should
not start at breakfast."""

import collections
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from typing import Any

from backend import timing
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json, resolve_within
from backend.services.path_access import ALLOWED_BROWSE_ROOTS

STATE_FILE = os.path.join(DATA_DIR, "user_scripts.json")
RUNS_FILE = os.path.join(DATA_DIR, "user_scripts_runs.json")

MAX_SCRIPTS = 20
MAX_NAME = 60
MAX_BODY_BYTES = 64 * 1024
OUTPUT_KEPT_BYTES = 16 * 1024  # the end of what a run printed
RUNS_KEPT = 20  # per script
DEFAULT_TIMEOUT_MIN = 30
MAX_TIMEOUT_MIN = 12 * 60
MAX_AT_ONCE = 2
KINDS = ("manual", "hourly", "daily", "weekly")
WORK_DIR = "/var/tmp"
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

_LOCK = threading.Lock()
_RUNNING: dict[str, dict[str, Any]] = {}  # script id -> {"started", "how", "who", "proc"}
_FIRED: dict[str, str] = {}  # script id -> the minute it last started on its schedule
_LIMIT_OK: dict[str, Any] = {"at": 0.0, "ok": False}


class ScriptError(ValueError):
    """What is wrong with a script as it was sent; `key` names the sentence for the screen."""

    def __init__(self, key: str, message: str, **params: Any):
        super().__init__(message)
        self.key = key
        self.params = params  # the numbers in the sentence, for the reader's language


# --- what is kept -------------------------------------------------------------------------------
def _read() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    data = data if isinstance(data, dict) else {}
    scripts = [s for s in data.get("scripts") or [] if isinstance(s, dict) and s.get("id")]
    return {"enabled": bool(data.get("enabled", False)), "scripts": scripts}


def enabled() -> bool:
    return _read()["enabled"]


def scripts() -> list[dict[str, Any]]:
    return _read()["scripts"]


def get(script_id: str) -> dict[str, Any] | None:
    return next((s for s in scripts() if s["id"] == script_id), None)


@json_locked(lambda *a, **k: STATE_FILE)
def set_enabled(on: bool) -> bool:
    data = _read()
    data["enabled"] = bool(on)
    atomic_write_json(STATE_FILE, data)
    return data["enabled"]


def _clean_schedule(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    kind = str(raw.get("kind") or "manual")
    if kind not in KINDS:
        raise ScriptError("bad_schedule", "Unknown schedule.")
    out: dict[str, Any] = {"kind": kind}
    if kind == "hourly":
        minute = raw.get("minute", 0)
        if not isinstance(minute, int) or isinstance(minute, bool) or not 0 <= minute <= 59:
            raise ScriptError("bad_time", "The minute must be between 0 and 59.")
        out["minute"] = minute
    if kind in ("daily", "weekly"):
        at = str(raw.get("at") or "")
        if not HHMM.match(at):
            raise ScriptError("bad_time", "The time must look like 03:30.")
        out["at"] = at
    if kind == "weekly":
        days = sorted(
            {d for d in raw.get("days") or [] if isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6}
        )
        if not days:
            raise ScriptError("no_days", "Choose at least one day.")
        out["days"] = days
    return out


def _clean_folder(raw: Any) -> str:
    folder = str(raw or "").strip()
    if not folder:
        return ""
    real = resolve_within(folder, ALLOWED_BROWSE_ROOTS)
    if real is None or not os.path.isdir(real):
        raise ScriptError("bad_folder", "That folder is not one of the NAS's shared folders.")
    data = os.path.realpath(DATA_DIR)
    if real == data or real.startswith(data.rstrip(os.sep) + os.sep):
        # the limited view covers Kiboto's own data; a folder inside it would be covered too
        raise ScriptError("bad_folder", "That folder is not one of the NAS's shared folders.")
    return real


def clean(raw: dict[str, Any]) -> dict[str, Any]:
    """A script as it may be kept, or ScriptError saying what is wrong with it."""
    name = " ".join(str(raw.get("name") or "").split())
    if not 1 <= len(name) <= MAX_NAME:
        raise ScriptError("bad_name", f"Give the script a name of up to {MAX_NAME} characters.", value=MAX_NAME)
    body = str(raw.get("body") or "").replace("\r\n", "\n")
    if not body.strip():
        raise ScriptError("empty", "The script is empty.")
    if "\x00" in body or len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise ScriptError(
            "too_long", f"A script can be up to {MAX_BODY_BYTES // 1024} KB of text.", value=MAX_BODY_BYTES // 1024
        )
    timeout = raw.get("timeout_min", DEFAULT_TIMEOUT_MIN)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= MAX_TIMEOUT_MIN:
        raise ScriptError(
            "bad_timeout", f"The time limit must be between 1 and {MAX_TIMEOUT_MIN} minutes.", value=MAX_TIMEOUT_MIN
        )
    return {
        "name": name,
        "body": body,
        "schedule": _clean_schedule(raw.get("schedule")),
        "enabled": bool(raw.get("enabled", True)),
        "limit_folder": _clean_folder(raw.get("limit_folder")),
        "timeout_min": timeout,
    }


@json_locked(lambda *a, **k: STATE_FILE)
def save(raw: dict[str, Any], script_id: str | None = None) -> dict[str, Any]:
    """Adds a script, or changes the one with this id. Raises ScriptError or KeyError (no such script)."""
    fresh = clean(raw)
    data = _read()
    if script_id is None:
        if len(data["scripts"]) >= MAX_SCRIPTS:
            raise ScriptError("too_many", f"There can be up to {MAX_SCRIPTS} scripts.", value=MAX_SCRIPTS)
        fresh["id"] = uuid.uuid4().hex[:12]
        fresh["created"] = time.time()
        data["scripts"].append(fresh)
    else:
        old = next((s for s in data["scripts"] if s["id"] == script_id), None)
        if old is None:
            raise KeyError(script_id)
        fresh["id"], fresh["created"] = old["id"], old.get("created")
        data["scripts"][data["scripts"].index(old)] = fresh
    atomic_write_json(STATE_FILE, data)
    return fresh


@json_locked(lambda *a, **k: STATE_FILE)
def _drop(script_id: str) -> bool:
    data = _read()
    kept = [s for s in data["scripts"] if s["id"] != script_id]
    if len(kept) == len(data["scripts"]):
        return False
    data["scripts"] = kept
    atomic_write_json(STATE_FILE, data)
    return True


@json_locked(lambda *a, **k: RUNS_FILE)
def _forget_runs(script_id: str) -> None:
    runs = read_json(RUNS_FILE, {})
    if isinstance(runs, dict) and runs.pop(script_id, None) is not None:
        atomic_write_json(RUNS_FILE, runs)


def delete(script_id: str) -> bool:
    """Takes a script away, with the record of its runs. A run that is going is stopped first."""
    stop(script_id)
    if not _drop(script_id):
        return False
    _forget_runs(script_id)
    return True


# --- the record of runs -------------------------------------------------------------------------
def runs(script_id: str) -> list[dict[str, Any]]:
    data = read_json(RUNS_FILE, {})
    found = data.get(script_id) if isinstance(data, dict) else None
    return [r for r in found or [] if isinstance(r, dict)]


@json_locked(lambda *a, **k: RUNS_FILE)
def _note_run(script_id: str, run: dict[str, Any]) -> None:
    data = read_json(RUNS_FILE, {})
    data = data if isinstance(data, dict) else {}
    data[script_id] = [run, *[r for r in data.get(script_id) or [] if isinstance(r, dict)]][:RUNS_KEPT]
    atomic_write_json(RUNS_FILE, data)


def last_run(script_id: str) -> dict[str, Any] | None:
    found = runs(script_id)
    return found[0] if found else None


def running() -> dict[str, dict[str, Any]]:
    with _LOCK:
        return {sid: {"started": r["started"], "how": r["how"], "who": r["who"]} for sid, r in _RUNNING.items()}


# --- limited to one folder ----------------------------------------------------------------------
# Runs as the first process of new mount and process namespaces, still with every right, and gives
# the rights up before the person's script starts. $1 is the folder, $2 Kiboto's data folder, the
# rest is the command.
#   - the folder becomes a mount of its own, so it stays writable when the rest does not;
#   - /tmp is a fresh scratch space; Kiboto's data (people, keys) is covered by an empty one;
#   - /dev keeps only the harmless devices: the drives themselves are not reachable;
#   - the apps' control socket is covered: a script with it could start an app with any right;
#   - every other mount becomes read-only. One that will not is a reason to stop, not to go on;
#   - setpriv then drops the rights that could undo this (mounting, raw devices, new namespaces),
#     for the script and everything it starts.
LIMIT_WRAP = r"""
set -u
F="$1"; DATA="$2"; shift 2
mount --bind "$F" "$F" || { echo "kiboto: the folder could not be set apart" >&2; exit 97; }
mount -t tmpfs -o size=256m,mode=1777 tmpfs /tmp || exit 97
[ -d "$DATA" ] && { mount -t tmpfs -o size=1m,mode=0755 tmpfs "$DATA" || exit 97; }
mount -t tmpfs -o size=1m,mode=0755 tmpfs /dev || exit 97
mknod -m 666 /dev/null c 1 3 && mknod -m 666 /dev/zero c 1 5 && mknod -m 666 /dev/full c 1 7 \
  && mknod -m 666 /dev/random c 1 8 && mknod -m 666 /dev/urandom c 1 9 && mknod -m 666 /dev/tty c 5 0 || exit 97
ln -s /proc/self/fd /dev/fd; ln -s /proc/self/fd/0 /dev/stdin; ln -s /proc/self/fd/1 /dev/stdout; ln -s /proc/self/fd/2 /dev/stderr
for sock in /var/run/docker.sock /run/docker.sock; do
  [ -e "$sock" ] && { mount --bind /dev/null "$sock" || exit 97; }
done
while read -r _ _ _ _ mp _; do
  mp=$(printf '%b' "$mp")
  # what lay under the old /proc and /dev is covered by the fresh ones (themselves made read-only)
  # and cannot be reached any more
  case "$mp" in "$F"|/tmp|/proc/*|/dev/*) continue ;; esac
  mount -o remount,bind,ro "$mp" 2>/dev/null || { echo "kiboto: $mp could not be made read-only" >&2; exit 97; }
done < /proc/self/mountinfo
cd "$F" || exit 97
exec setpriv --bounding-set=-all,+chown,+dac_override,+dac_read_search,+fowner,+kill,+setgid,+setuid \
  --inh-caps=-all --no-new-privs "$@"
"""
LIMIT_FAILED = 97  # the wrap's own exit code: the limit could not be set up, so the script did not start


def limit_available(now: float | None = None) -> bool:
    """Whether this system can limit a script to a folder (it needs unshare, setpriv and the right
    to make a mount namespace). Asked at most every ten minutes."""
    now = time.time() if now is None else now
    if now - _LIMIT_OK["at"] < 600:
        return bool(_LIMIT_OK["ok"])
    ok = bool(shutil.which("unshare") and shutil.which("setpriv") and shutil.which("mount"))
    if ok:
        try:
            ok = subprocess.run(["unshare", "--mount", "true"], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
    _LIMIT_OK.update(at=now, ok=ok)
    return ok


def command(script: dict[str, Any], path: str) -> list[str]:
    """What is started for this script kept at `path`."""
    own = [path] if script["body"].startswith("#!") else [shutil.which("bash") or "sh", path]
    folder = script.get("limit_folder") or ""
    if not folder:
        return own
    return [
        "unshare", "--mount", "--pid", "--fork", "--mount-proc", "--propagation", "private", "--",
        "sh", "-c", LIMIT_WRAP, "kiboto-limit", folder, os.path.realpath(DATA_DIR), *own,
    ]  # fmt: skip


# --- running ------------------------------------------------------------------------------------
class NotNow(RuntimeError):
    """A run that cannot start; `key` names the sentence for the screen."""

    def __init__(self, key: str, message: str):
        super().__init__(message)
        self.key = key
        self.params: dict[str, Any] = {}


def start(script_id: str, how: str, who: str = "") -> dict[str, Any]:
    """Starts a run in the background and says when it started. Raises KeyError (no such script)
    or NotNow (scripts are off, this one is running, too many are, or the limit cannot be set up)."""
    script = get(script_id)
    if script is None:
        raise KeyError(script_id)
    if not enabled():
        raise NotNow("off", "Scripts are turned off.")
    if script.get("limit_folder") and not limit_available():
        raise NotNow("no_limit", "This system cannot limit a script to a folder, so it was not started.")
    with _LOCK:
        if script_id in _RUNNING:
            raise NotNow("running", "This script is already running.")
        if len(_RUNNING) >= MAX_AT_ONCE:
            raise NotNow("busy", "Other scripts are running. Try again when one has finished.")
        entry = {"started": time.time(), "how": how, "who": who, "proc": None}
        _RUNNING[script_id] = entry
    threading.Thread(target=_run, args=(script, entry), daemon=True, name=f"script-{script_id}").start()
    return {"started": entry["started"]}


def stop(script_id: str) -> bool:
    """Stops a run that is going (the script and everything it started)."""
    with _LOCK:
        proc = (_RUNNING.get(script_id) or {}).get("proc")
        if proc is None:
            return False
        _RUNNING[script_id]["stopped"] = True
    _kill(proc)
    return True


def _kill(proc: Any) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        logger.debug("[Scripts] the run had already ended", exc_info=True)


def _collect(stream: Any, tail: "collections.deque[bytes]", seen: list[int]) -> None:
    """Reads what the run prints, keeping the end: a script that prints for hours fills no disk."""
    kept = 0
    for chunk in iter(lambda: stream.read(4096), b""):
        seen[0] += len(chunk)
        tail.append(chunk)
        kept += len(chunk)
        while kept - len(tail[0]) >= OUTPUT_KEPT_BYTES:
            kept -= len(tail.popleft())


def _run(script: dict[str, Any], entry: dict[str, Any]) -> None:
    sid, started = script["id"], entry["started"]
    # not under /tmp: the limited view gets a /tmp of its own, and the script must still be there
    work = tempfile.mkdtemp(prefix="kiboto-script-", dir=WORK_DIR if os.path.isdir(WORK_DIR) else None)
    code: int | None = None
    timed_out = False
    tail: collections.deque[bytes] = collections.deque()
    seen = [0]
    try:
        path = os.path.join(work, "script")
        with open(path, "w", encoding="utf-8") as f:
            f.write(script["body"])
        os.chmod(path, 0o700)
        env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/tmp",
            "LANG": "C.UTF-8",
            "KIBOTO_SCRIPT": script["name"],
        }
        proc = subprocess.Popen(  # noqa: S603  the administrator's own script: running it is the feature
            command(script, path),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=script.get("limit_folder") or "/",
            env=env,
            start_new_session=True,
        )
        with _LOCK:
            entry["proc"] = proc
        reader = threading.Thread(target=_collect, args=(proc.stdout, tail, seen), daemon=True)
        reader.start()
        try:
            code = proc.wait(timeout=int(script.get("timeout_min") or DEFAULT_TIMEOUT_MIN) * 60)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(proc)
            code = proc.wait()
        reader.join(timeout=10)
    except OSError as e:
        tail.append(f"kiboto: the script could not be started: {e}\n".encode())
        seen[0] += len(tail[-1])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with _LOCK:
        stopped = bool(entry.get("stopped"))
    output = b"".join(tail)[-OUTPUT_KEPT_BYTES:].decode("utf-8", "replace")
    run = {
        "started": started,
        "ended": time.time(),
        "how": entry["how"],
        "who": entry["who"],
        "exit_code": code,
        "timed_out": timed_out,
        "stopped": stopped and not timed_out,
        "limit_failed": code == LIMIT_FAILED and bool(script.get("limit_folder")),
        "output": output,
        "output_bytes": seen[0],
    }
    run["ok"] = code == 0 and not timed_out and not run["stopped"]
    try:
        _finish(script, run)
    finally:
        # only now is it no longer running: someone who asks in between sees "running", never
        # "not running, and no result yet" (a screen that looks again only while something runs
        # would stop looking and miss the result)
        with _LOCK:
            _RUNNING.pop(sid, None)


def _finish(script: dict[str, Any], run: dict[str, Any]) -> None:
    """The run goes on record, in the security log, and (a scheduled run that failed) to the alerts."""
    try:
        _note_run(script["id"], run)
    except OSError:
        logger.warning("[Scripts] the run of %s could not be recorded", script["name"], exc_info=True)
    try:
        from backend.users_db import log_security_event

        log_security_event(
            "scripts.run",
            "success" if run["ok"] else "failure",
            actor_username=run["who"] or None,
            details={
                "script": script["name"],
                "how": run["how"],
                "exit_code": run["exit_code"],
                "timed_out": run["timed_out"],
                "seconds": round(run["ended"] - run["started"], 1),
                "limited_to": script.get("limit_folder") or "",
            },
        )
    except (OSError, RuntimeError, ValueError):
        logger.warning(
            "[Scripts] the run of %s could not be written to the security log", script["name"], exc_info=True
        )
    if run["how"] == "schedule" and not run["ok"]:
        from backend.state import add_event, event_text

        why = "timeout" if run["timed_out"] else "limit" if run["limit_failed"] else "code"
        add_event(
            "warning",
            "Scheduled script",
            f"The script {script['name']} did not finish well ({why}, exit code {run['exit_code']}).",
            event_text(f"script_failed_{why}", name=script["name"], code=run["exit_code"]),
        )


# --- the timer ----------------------------------------------------------------------------------
def due(script: dict[str, Any], t: time.struct_time) -> bool:
    """Whether this script's schedule names this minute."""
    sched = script.get("schedule") or {}
    kind = sched.get("kind")
    if not script.get("enabled") or kind not in ("hourly", "daily", "weekly"):
        return False
    if kind == "hourly":
        return t.tm_min == int(sched.get("minute") or 0)
    if f"{t.tm_hour:02d}:{t.tm_min:02d}" != sched.get("at"):
        return False
    return kind == "daily" or t.tm_wday in (sched.get("days") or [])


def came_due(script: dict[str, Any], now: float) -> float:
    """When the minute of this script's schedule that is due now came: the one that has just come,
    or passed a few minutes ago (the scheduler does not look at every minute); 0 when none."""
    sched = script.get("schedule") or {}
    kind = sched.get("kind")
    if not script.get("enabled") or kind not in ("hourly", "daily", "weekly"):
        return 0.0
    if kind == "hourly":
        came = timing.minute_of_hour(int(sched.get("minute") or 0), now)
    else:
        came = timing.moment(str(sched.get("at") or ""), now)
    if came and kind == "weekly" and time.localtime(came).tm_wday not in (sched.get("days") or []):
        return 0.0
    return came


def _ran_for(script_id: str, came: float) -> bool:
    """Whether a run on the schedule began for that minute already: after a restart the list of
    what was started is empty, and the same minute must not start a script a second time."""
    last = last_run(script_id) or {}
    began = float(last.get("started") or 0)
    return last.get("how") == "schedule" and came <= began <= came + timing.WINDOW + 60


def run_due(now: float | None = None) -> list[str]:
    """Called about every minute by the scheduler: starts what is due, once for each minute a
    schedule names. Returns the ids started."""
    state = _read()
    if not state["enabled"]:
        return []
    now = time.time() if now is None else now
    started = []
    for script in state["scripts"]:
        came = came_due(script, now)
        minute = time.strftime("%Y-%m-%d %H:%M", time.localtime(came)) if came else ""
        if not minute or _FIRED.get(script["id"]) == minute:
            continue
        _FIRED[script["id"]] = minute
        if _ran_for(script["id"], came):
            continue
        try:
            start(script["id"], "schedule")
            started.append(script["id"])
        except NotNow as e:
            logger.warning("[Scripts] %s was due and did not start: %s", script["name"], e)
        except KeyError:
            continue
    return started


def next_run(script: dict[str, Any], now: float | None = None) -> float | None:
    """When the schedule next names a minute (within eight days), for the screen."""
    if not script.get("enabled") or (script.get("schedule") or {}).get("kind") in (None, "manual"):
        return None
    now = time.time() if now is None else now
    base = int(now // 60 + 1) * 60
    for i in range(8 * 24 * 60):
        if due(script, time.localtime(base + i * 60)):
            return float(base + i * 60)
    return None


def reset_for_tests() -> None:
    with _LOCK:
        _RUNNING.clear()
    _FIRED.clear()
    _LIMIT_OK.update(at=0.0, ok=False)
