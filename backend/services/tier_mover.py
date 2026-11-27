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


ACL_XATTR = "system.posix_acl_access"
ACL_DEFAULT_XATTR = "system.posix_acl_default"  # what files made in a folder start with


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


DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _walk(root: str, parts: list[str]) -> int:
    """An open folder at root/parts..., each step opened without following a link: a link anywhere
    on the way is refused (OSError), so nothing outside the folder is reached. On Kiboto OS this
    runs as root on the machine itself, where a link in a shared folder could point anywhere."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts:
            nxt = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nxt
    except OSError:
        os.close(fd)
        raise
    return fd


def _folders_like(fast_root: str, slow_root: str, parts: list[str]) -> int:
    """The folders on the slow side that lead to the file, made where missing to belong to who the
    fast ones belong to, with their rights. Returns the last one open. Each step is opened without
    following a link, and owner and rights are set on the open folder, never by its name."""
    fast = os.open(fast_root, os.O_RDONLY | os.O_DIRECTORY)
    slow = os.open(slow_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts:
            nfast = os.open(part, DIR_FLAGS, dir_fd=fast)
            os.close(fast)
            fast = nfast
            try:
                nslow = os.open(part, DIR_FLAGS, dir_fd=slow)
            except FileNotFoundError:
                os.mkdir(part, 0o700, dir_fd=slow)
                nslow = os.open(part, DIR_FLAGS, dir_fd=slow)
                like = os.fstat(fast)
                acls_like(fast, nslow, folder=True)
                os.fchown(nslow, like.st_uid, like.st_gid)
                os.fchmod(nslow, stat.S_IMODE(like.st_mode))
            os.close(slow)
            slow = nslow
    except OSError:
        os.close(slow)
        raise
    finally:
        os.close(fast)
    return slow


def _copy_xattrs(src: int, dst: int) -> None:
    """Extended attributes (ACLs among them), as shutil.copystat would; one that cannot be set stays behind."""
    try:
        names = os.listxattr(src)
    except OSError:
        return
    for name in names:
        try:
            os.setxattr(dst, name, os.getxattr(src, name))
        except OSError as e:
            if e.errno not in (errno.ENOTSUP, errno.EPERM, errno.EACCES):
                raise


def move_one(fast_root: str, slow_root: str, rel: str, keep_free: int = ROOM_KEPT) -> tuple[str, int]:
    """Moves one file; returns how it went ("moved", or why not) and the bytes moved. Every name is
    taken relative to an open folder and opened without following a link, so a file or a folder
    swapped for a link while it is looked at cannot send the copy, the owner or the rights anywhere."""
    parts = rel.split("/")
    if not rel or rel.startswith("/") or any(p in ("", ".", "..") for p in parts):
        return "outside", 0
    name, dirs = parts[-1], parts[:-1]
    try:
        sdir = _walk(fast_root, dirs)
    except FileNotFoundError:
        return "gone", 0
    except OSError:
        return "outside", 0  # a link on the way, or not a folder
    ddir = -1
    try:
        try:
            before = os.stat(name, dir_fd=sdir, follow_symlinks=False)
        except FileNotFoundError:
            return "gone", 0
        if not stat.S_ISREG(before.st_mode) or before.st_nlink > 1:
            return "not_plain", 0  # a link, or a file with a second name: moving it would break the other
        if in_use(os.path.join(fast_root, rel)):
            return "in_use", 0
        room = os.statvfs(slow_root)
        if room.f_bavail * room.f_frsize < before.st_size + max(keep_free, ROOM_KEPT):
            return "no_room", 0
        ddir = _folders_like(fast_root, slow_root, dirs)
        if _there(name, ddir):
            return "already_there", 0
        return _copy_and_swap(sdir, ddir, name, before)
    finally:
        os.close(sdir)
        if ddir >= 0:
            os.close(ddir)


def _there(name: str, dir_fd: int) -> bool:
    try:
        os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def acls_like(src: int, dst: int, folder: bool = False) -> None:
    """The copy gets the access lists the original has, and no other. A list the copy took from
    the folder it was made in goes: the slow side's folder hands down group::r-x (it lets
    Kiboto's own user in), keeping the mode then only lowers the mask, and Samba, which writes
    as the folder's group, could no longer change a file once it had moved."""
    _copy_xattrs(src, dst)
    try:
        have = set(os.listxattr(src))
    except OSError:
        return
    for name in (ACL_XATTR, ACL_DEFAULT_XATTR) if folder else (ACL_XATTR,):
        if name in have:
            continue
        try:
            os.removexattr(dst, name)
        except OSError as e:
            if e.errno not in (errno.ENODATA, errno.ENOTSUP, errno.EPERM, errno.EACCES):
                raise


def _copy_and_swap(sdir: int, ddir: int, name: str, before: os.stat_result) -> tuple[str, int]:
    part = name + PART
    made = False
    try:
        # opened by name in the open folder, never following a link (and the file keeps its name)
        with open(name, "rb", opener=lambda n, f: os.open(n, f | os.O_NOFOLLOW, dir_fd=sdir)) as src:
            opened = os.fstat(src.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                return "changed", 0  # another file took its name meanwhile
            new_file = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            with open(part, "wb", opener=lambda n, f: os.open(n, new_file, 0o600, dir_fd=ddir)) as dst:
                made = True
                shutil.copyfileobj(src, dst, 8 * 1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
                acls_like(src.fileno(), dst.fileno())
                os.fchown(dst.fileno(), before.st_uid, before.st_gid)
                os.fchmod(dst.fileno(), stat.S_IMODE(before.st_mode))
                os.utime(dst.fileno(), ns=(before.st_atime_ns, before.st_mtime_ns))
                copied = os.fstat(dst.fileno()).st_size
        after = os.stat(name, dir_fd=sdir, follow_symlinks=False)
        if (
            not _same(before, after)
            or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            or copied != before.st_size
        ):
            os.unlink(part, dir_fd=ddir)
            made = False
            return "changed", 0  # someone wrote to it while it was copied: it stays, and is tried another night
        os.replace(part, name, src_dir_fd=ddir, dst_dir_fd=ddir)
        made = False
        os.fsync(ddir)
        os.unlink(name, dir_fd=sdir)
    except (OSError, Stopped):
        if made and _there(part, ddir):
            os.unlink(part, dir_fd=ddir)
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
            how, size = move_one(fast, slow, rel, int(job.get("keep_free") or 0))
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
