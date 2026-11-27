"""Off-site backups on Kiboto OS read every file of the folders they back up (ADR 0006).

Kiboto's web process runs as its own user there, and each person's private folder belongs to that
person's own system account (owner only). restic, started by the web process, could not read those
folders, so every backup left them out ("N files could not be read").

Here the root service runs `restic backup` for one backup as Kiboto's user with one extra right,
CAP_DAC_READ_SEARCH (read any file), in a service of its own. The root service builds the command
itself from the backup's record: only folders inside the storage folder, and the host name and tag
Kiboto's file backups carry; nothing the web process sends becomes an argument. The key is read by
the root service without following links and handed over in a root-only environment file. restic
writes the backup as Kiboto's user, so it stays the web process's to read, and its output goes to
files Kiboto's user opens itself (the shell's redirect, never the root service)."""

from __future__ import annotations

import os
import re
import shutil
import stat
import threading
import time
from collections.abc import Callable
from typing import Any

from backend.config import DATA_DIR, POOL_PATH, logger

RUN_DIR = os.path.join(DATA_DIR, "offsite_run")  # the web user's: restic's output, its exit code
ENV_DIR = "/run/kiboto-offsite"  # root's: one environment file per running backup
LIMIT_SECS = 6 * 3600
CAPS = "CAP_DAC_READ_SEARCH"
# a restore keeps each file's owner and mode: root, with only the rights over files, and a machine that
# is read-only but for the restore folder (a link planted in it cannot lead a write anywhere else)
RESTORE_CAPS = "CAP_CHOWN CAP_DAC_OVERRIDE CAP_DAC_READ_SEARCH CAP_FOWNER CAP_FSETID"
ENV_KEYS = ("RESTIC_REPOSITORY", "RCLONE_CONFIG", "RESTIC_CACHE_DIR", "RESTIC_PROGRESS_FPS")
SECRET_KEYS = ("RESTIC_REST_USERNAME", "RESTIC_REST_PASSWORD")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")  # offsite_backup's names for a backup


class NotHere(RuntimeError):
    """This backup is run by the web process as before (a folder outside the storage folder, an
    rclone location, no root service)."""


def unit(repo_id: str, what: str = "read") -> str:
    return f"kiboto-offsite-{what}-{repo_id}"


def out_base(repo_id: str) -> str:
    return os.path.join(RUN_DIR, repo_id)


# --- the root service's side -----------------------------------------------------------------------
def _inside_storage(paths: Any) -> list[str]:
    root = os.path.realpath(POOL_PATH).rstrip(os.sep) + os.sep
    if not isinstance(paths, list) or not paths or len(paths) > 50:
        raise ValueError("Not reading: no folders, or too many.")
    out = []
    for p in paths:
        real = os.path.realpath(p) if isinstance(p, str) and p.startswith("/") and "\0" not in p else ""
        if not real or not (real + os.sep).startswith(root) or not os.path.exists(real):
            raise ValueError("Not reading: a folder of this backup is not in the storage folder.")
        out.append(real)
    return out


def _read_no_link(path: str, owner: int) -> str:
    """A small file of Kiboto's user, read without following a link to someone else's file."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != owner or st.st_size > 4096:
            raise ValueError("Not reading: the backup's key is not Kiboto's own file.")
        return os.read(fd, 4096).decode().strip()
    finally:
        os.close(fd)


def _env_text(values: dict[str, str]) -> str:
    lines = []
    for k, v in values.items():
        if "\n" in v or "\r" in v or "\0" in v:
            raise ValueError("Not reading: a setting of this backup has a line break.")
        lines.append(f"{k}={v}")
    return "\n".join(lines) + "\n"


def read_with(
    repo_id: str,
    repo: dict[str, Any],
    restic_env: dict[str, str],
    key_file: str,
    marks: tuple[str, str],
    run: Callable[..., tuple[int, str]] | None = None,
) -> dict[str, Any]:
    """The root service's operation (offsite_backup.read_here hands it the backup's record, restic's
    settings, the key's file and the host name and tag): runs restic backup with the right to read
    every file of its folders, and waits for it. Answers {"done": True}; restic's own exit code is
    in out_base(repo_id) + ".code"."""
    from backend.services.web_user import USER

    if run is None:
        from backend.services.host_basics import run
    import pwd

    if not _ID.match(repo_id or ""):
        raise ValueError("Not reading: that is not a backup's name.")
    location = str(repo["location"])
    if location.startswith("rclone:"):
        raise ValueError("Not reading here: rclone locations are backed up by Kiboto itself.")
    paths = _inside_storage(repo.get("paths"))
    who = pwd.getpwnam(USER)
    restic = shutil.which("restic") or "/usr/bin/restic"
    env = {k: v for k, v in restic_env.items() if k in ENV_KEYS or k in SECRET_KEYS}
    env["RESTIC_PASSWORD"] = _read_no_link(key_file, who.pw_uid)
    env["KB_OUT"] = out_base(repo_id)
    env["HOME"] = DATA_DIR
    os.makedirs(ENV_DIR, mode=0o700, exist_ok=True)
    env_file = os.path.join(ENV_DIR, f"{repo_id}.env")
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(_env_text(env))
    args = ["backup", "--json", "--host", marks[0], "--tag", marks[1], "--exclude", ".RecycleBin", *paths]
    cmd = ["systemd-run", "--wait", "--quiet", "--collect", "--unit", unit(repo_id)]
    cmd += ["--description", "Kiboto: off-site backup, reading every file of its folders"]
    cmd += ["-p", f"User={USER}", "-p", f"Group={who.pw_gid}", "-p", f"AmbientCapabilities={CAPS}"]
    cmd += ["-p", f"CapabilityBoundingSet={CAPS}", "-p", "NoNewPrivileges=yes", "-p", f"RuntimeMaxSec={LIMIT_SECS}"]
    cmd += ["-p", f"EnvironmentFile={env_file}", "--working-directory", "/"]
    cmd += ["/bin/sh", "-c", 'r="$1"; shift; "$r" "$@" >"$KB_OUT.out" 2>"$KB_OUT.err"; echo $? >"$KB_OUT.code"']
    cmd += ["kiboto-offsite", restic, *args]
    try:
        code, said = run(cmd, timeout=LIMIT_SECS + 120)
    finally:
        os.remove(env_file)
    if code != 0 and "code=exited" not in said:  # a restic that ended badly is in .code; this is systemd
        logger.warning("[Offsite] the reading backup of %s did not start: %s", repo_id, said[:200])
    return {"done": True}


def stop_here(repo_id: str, run: Callable[..., tuple[int, str]] | None = None) -> bool:
    if run is None:
        from backend.services.host_basics import run
    if not _ID.match(repo_id or ""):
        raise ValueError("Not stopping: that is not a backup's name.")
    return run(["systemctl", "stop", unit(repo_id), unit(repo_id, "restore")], timeout=60)[0] == 0


def restore_with(
    repo_id: str,
    repo: dict[str, Any],
    restic_env: dict[str, str],
    key_file: str,
    restore: tuple[str, str, str],
    in_storage: Callable[[str], bool],
    run: Callable[..., tuple[int, str]] | None = None,
) -> dict[str, Any]:
    """The root service's operation (offsite_backup.restore_here hands it the checked restore: the
    version, the path in it and the folder to restore into): restic restore as root with only the
    rights over files, keeping owners and modes, on a machine read-only but for that folder."""
    from backend.services.web_user import USER

    if run is None:
        from backend.services.host_basics import run
    import pwd

    snapshot, inside, target = restore
    if not _ID.match(repo_id or "") or str(repo["location"]).startswith("rclone:"):
        raise ValueError("Not restoring here: Kiboto restores this backup itself.")
    real = os.path.realpath(target) if target.startswith("/") and "\0" not in target else ""
    if not real or real != os.path.normpath(target) or not in_storage(real):
        raise ValueError("Not restoring: restore into a folder on the storage.")
    os.makedirs(real, exist_ok=True)
    if os.path.realpath(real) != real:
        raise ValueError("Not restoring: restore into a folder on the storage.")
    who = pwd.getpwnam(USER)
    restic = shutil.which("restic") or "/usr/bin/restic"
    env = {k: v for k, v in restic_env.items() if k in ENV_KEYS or k in SECRET_KEYS}
    env.pop("RESTIC_CACHE_DIR", None)
    env["RESTIC_PASSWORD"] = _read_no_link(key_file, who.pw_uid)
    env["KB_OUT"] = out_base(repo_id)
    env["HOME"] = "/tmp"
    os.makedirs(ENV_DIR, mode=0o700, exist_ok=True)
    env_file = os.path.join(ENV_DIR, f"{repo_id}.restore.env")
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(_env_text(env))
    args = ["--no-lock", "--no-cache", "restore", "--json", snapshot, "--target", real, "--include", inside]
    cmd = ["systemd-run", "--wait", "--quiet", "--collect", "--unit", unit(repo_id, "restore")]
    cmd += ["--description", "Kiboto: restore from an off-site backup, keeping owners"]
    cmd += ["-p", f"CapabilityBoundingSet={RESTORE_CAPS}", "-p", "NoNewPrivileges=yes", "-p", "ProtectSystem=strict"]
    cmd += ["-p", f"ReadWritePaths={real} {RUN_DIR}", "-p", "PrivateTmp=yes", "-p", f"RuntimeMaxSec={LIMIT_SECS}"]
    cmd += ["-p", f"EnvironmentFile={env_file}", "--working-directory", "/"]
    cmd += ["/bin/sh", "-c", 'r="$1"; shift; "$r" "$@" >"$KB_OUT.out" 2>"$KB_OUT.err"; echo $? >"$KB_OUT.code"']
    cmd += ["kiboto-offsite", restic, *args]
    try:
        code, said = run(cmd, timeout=LIMIT_SECS + 120)
    finally:
        os.remove(env_file)
    if code != 0 and "code=exited" not in said:
        logger.warning("[Offsite] the restore from %s did not start: %s", repo_id, said[:200])
    return {"done": True}


# --- the web process's side ------------------------------------------------------------------------
class _Running:
    """What offsite_backup keeps for a running restic, so Stop works the same: terminate()."""

    def __init__(self, repo_id: str):
        self.repo_id = repo_id

    def terminate(self) -> None:
        from backend import door

        try:
            door.call("offsite.stop_read", repo_id=self.repo_id, timeout=90)
        except (door.DoorError, OSError):
            logger.warning("[Offsite] the backup of %s could not be stopped", self.repo_id, exc_info=True)


def _follow(path: str, on_line: Callable[[str], Any], done: threading.Event) -> list[str]:
    """Hands each line restic writes to on_line, until `done` and nothing more is written. Once
    `done`, it looks one more time: lines written between its last look and the end were lost
    before, with restic's summary among them (found by CI, now and then)."""
    kept: list[str] = []
    last_look = False
    with open(path, encoding="utf-8", errors="replace") as f:
        part = ""
        while True:
            chunk = f.readline()
            if chunk:
                part += chunk
                if part.endswith("\n"):
                    if '"message_type":"status"' not in part:
                        kept.append(part)
                    try:
                        on_line(part)
                    except (ValueError, KeyError, TypeError, AttributeError):
                        logger.debug("offsite: progress line not understood", exc_info=True)
                    part = ""
                continue
            if last_look:
                return kept
            if done.is_set():
                last_look = True
                continue
            time.sleep(0.5)


def _text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def run(
    repo: dict[str, Any], on_line: Callable[[str], Any], running: dict[str, Any], op: str = "offsite.read", **args: Any
) -> tuple[int, str, str]:
    """Runs this backup's restic through the root service (`op`: the backup's reading run, or
    "offsite.restore" with its version, path and folder) and follows its output. Raises NotHere when
    the web process should run it itself."""
    from backend import door, runtime

    if not runtime.without_root() or not door.available():
        raise NotHere("no root service here")
    base = out_base(repo["id"])
    os.makedirs(RUN_DIR, mode=0o700, exist_ok=True)
    for end in (".out", ".err", ".code"):
        if os.path.lexists(base + end):
            os.remove(base + end)
    open(base + ".out", "w", encoding="utf-8").close()  # noqa: SIM115 - restic's shell writes into it
    done = threading.Event()
    kept: list[str] = []
    follower = threading.Thread(target=lambda: kept.extend(_follow(base + ".out", on_line, done)), daemon=True)
    follower.start()
    running[repo["id"]] = _Running(repo["id"])
    try:
        door.call(op, repo_id=repo["id"], timeout=LIMIT_SECS + 300, **args)
    except door.DoorError as e:
        if e.kind == "value" or str(e).startswith("no such operation"):
            raise NotHere(str(e)) from None
        raise
    finally:
        running.pop(repo["id"], None)
        done.set()
        follower.join(30)
    said = _text(base + ".code").strip()
    code = int(said) if said.lstrip("-").isdigit() else 1
    return code, "".join(kept), _text(base + ".err")
