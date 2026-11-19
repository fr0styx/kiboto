"""Moves the files of one tiering run from the fast pool to the slow one (data tiering, 19 Nov 2026).

Run on its own, in a short-lived container that sees only the folder's fast side (/fast), its
slow side (/slow) and the job's own folder: `python3 /app/backend/services/tier_mover.py /job/job.json`.
Kiboto chose the files; this only moves them, and for each one it is careful in the same order:

  1. a file someone has open is left alone;
  2. it is copied to the slow side under a temporary name and written through to the drive;
  3. the copy is checked against the original, and the original must not have changed meanwhile;
  4. only then does the copy get its real name, and only after that is the original removed.

A file that is already on the slow side under the same name is never replaced. Whatever stops a
file from moving leaves it where it was."""

import errno
import fcntl
import json
import os
import shutil
import signal
import stat
import sys
import time
from typing import Any

PART = ".kiboto-moving"
ERRORS_LISTED = 50
ROOM_KEPT = 64 * 1024 * 1024  # the slow side is never filled to the last byte
NO_POINT_GOING_ON = (errno.ENOSPC, errno.EDQUOT, errno.EROFS)
F_SETLEASE = 1024
F_UNLCK = 2
F_WRLCK = 1


class Stopped(Exception):
    """Kiboto asked the run to end: the file in hand is left where it was."""


def _stop(_signum: int, _frame: Any) -> None:
    raise Stopped()


def in_use(path: str) -> bool:
    """True when someone has the file open: the kernel grants a write lease only on a file nobody
    else has open. A filesystem that cannot say (it has no leases) counts as not in use."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return True
    try:
        fcntl.fcntl(fd, F_SETLEASE, F_WRLCK)
    except OSError as e:
        return e.errno in (errno.EAGAIN, errno.EACCES, errno.EBUSY)
    else:
        fcntl.fcntl(fd, F_SETLEASE, F_UNLCK)
        return False
    finally:
        os.close(fd)


def _same(a: os.stat_result, b: os.stat_result) -> bool:
    return a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns


def _folders_like(fast_root: str, slow_root: str, rel_dir: str) -> None:
    """The folders on the slow side that lead to the file, made to belong to who the fast ones belong to."""
    walked = ""
    for part in [p for p in rel_dir.split("/") if p]:
        walked = os.path.join(walked, part)
        target = os.path.join(slow_root, walked)
        if not os.path.isdir(target):
            os.mkdir(target)
            like = os.stat(os.path.join(fast_root, walked))
            os.chown(target, like.st_uid, like.st_gid)
            os.chmod(target, stat.S_IMODE(like.st_mode))


def move_one(fast_root: str, slow_root: str, rel: str) -> tuple[str, int]:
    """Moves one file; returns how it went ("moved", or why not) and the bytes moved."""
    src, dst = os.path.join(fast_root, rel), os.path.join(slow_root, rel)
    real_fast = os.path.realpath(fast_root)
    real_dir = os.path.realpath(os.path.dirname(src))
    if (real_dir != real_fast and not real_dir.startswith(real_fast + "/")) or ".." in rel.split("/"):
        return "outside", 0
    try:
        before = os.lstat(src)
    except OSError:
        return "gone", 0
    if not stat.S_ISREG(before.st_mode) or before.st_nlink > 1:
        return "not_plain", 0  # a link, or a file with a second name: moving it would break the other
    if os.path.lexists(dst):
        return "already_there", 0
    if in_use(src):
        return "in_use", 0
    room = os.statvfs(slow_root)
    if room.f_bavail * room.f_frsize < before.st_size + ROOM_KEPT:
        return "no_room", 0
    part = dst + PART
    try:
        _folders_like(fast_root, slow_root, os.path.dirname(rel))
        with open(src, "rb") as fin, open(part, "wb") as fout:
            shutil.copyfileobj(fin, fout, 8 * 1024 * 1024)
            fout.flush()
            os.fsync(fout.fileno())
        shutil.copystat(src, part)
        os.chown(part, before.st_uid, before.st_gid)
        if not _same(before, os.lstat(src)) or os.path.getsize(part) != before.st_size:
            os.unlink(part)
            return "changed", 0  # someone wrote to it while it was copied: it stays, and is tried another night
        os.replace(part, dst)
        fd = os.open(os.path.dirname(dst), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.unlink(src)
    except (OSError, Stopped):
        if os.path.lexists(part):
            os.unlink(part)
        raise
    return "moved", before.st_size


def run(job: dict[str, Any]) -> dict[str, Any]:
    fast, slow = job["fast"], job["slow"]
    out: dict[str, Any] = {"started": time.time(), "moved": [], "bytes": 0, "counts": {}, "errors": [], "stopped": ""}
    if os.path.isdir(fast) and os.path.isdir(slow):
        like = os.stat(fast)
        if os.stat(slow).st_uid != like.st_uid:  # made just now for this run: it belongs to who the folder does
            os.chown(slow, like.st_uid, like.st_gid)
            os.chmod(slow, stat.S_IMODE(like.st_mode))
    for rel in job.get("files") or []:
        try:
            how, size = move_one(fast, slow, rel)
        except Stopped:
            out["stopped"] = "asked"
            break
        except OSError as e:
            how, size = "error", 0
            if len(out["errors"]) < ERRORS_LISTED:
                out["errors"].append({"file": rel, "why": e.strerror or str(e)})
            if e.errno in NO_POINT_GOING_ON:
                how = "no_room"
        out["counts"][how] = out["counts"].get(how, 0) + 1
        if how == "moved":
            out["moved"].append(rel)
            out["bytes"] += size
        elif how == "no_room":
            out["stopped"] = "full"  # the rest would fail the same way, and each try opens a file
            break
    out["ended"] = time.time()
    return out


def main(argv: list[str]) -> int:
    with open(argv[1], encoding="utf-8") as f:
        job = json.load(f)
    signal.signal(signal.SIGTERM, _stop)
    result = run(job)
    target = os.path.join(os.path.dirname(argv[1]), "result.json")
    with open(target + ".new", "w", encoding="utf-8") as f:
        f.write(json.dumps(result))
        f.flush()
        os.fsync(f.fileno())
    os.replace(target + ".new", target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
