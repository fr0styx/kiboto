"""Files and folders Kiboto makes for a person belong to the folder they are made in.

Kiboto runs as root. A file root makes is root's own, and others may read it and change nothing.
A file uploaded through the Files app could then be opened over the network share and not be
changed, renamed or deleted there, and nothing could be put into a folder made in the Files app.

So what Kiboto makes inside a folder takes that folder's owner and group. Where the folder lets
its group or everyone write, they may write here too (a shared folder on Unraid is open that way;
one of Kiboto's own is written as its owner). Rights are only added, never taken away, and only
something this process's own user owns is touched: what Kiboto made a moment ago, never a file of
someone else's that was there before.

A filesystem without owners (exFAT or NTFS on a USB drive) refuses; that is not an error.
"""

from __future__ import annotations

import grp
import os
import pwd
import stat
from collections.abc import Callable

from backend.config import logger


def _me() -> int:
    return os.geteuid()


def _rights(folder_mode: int, own: int) -> int:
    """`own` with the right to write added for the group and for everyone, where the folder gives
    it to them and they may read here."""
    for shift in (3, 0):
        if (folder_mode >> shift) & 0o2 and (own >> shift) & 0o4:
            own |= 0o2 << shift
    return own


def like_folder(path: str) -> bool:
    """Gives `path`, which Kiboto just made, the owner and group of the folder it is in, and that
    folder's right to write. False when nothing was changed."""
    try:
        st = os.lstat(path)
        folder = os.stat(os.path.dirname(os.path.abspath(path)))
    except OSError:
        return False
    me = _me()
    if st.st_uid != me:
        return False  # not made by Kiboto: left as it is
    changed = False
    try:
        if not stat.S_ISLNK(st.st_mode):
            now, want = stat.S_IMODE(st.st_mode), _rights(stat.S_IMODE(folder.st_mode), stat.S_IMODE(st.st_mode))
            if want != now:
                os.chmod(path, want)
                changed = True
        if me == 0 and (st.st_uid, st.st_gid) != (folder.st_uid, folder.st_gid):
            os.lchown(path, folder.st_uid, folder.st_gid)
            changed = True
    except OSError as e:
        logger.debug("[Files] %s keeps the owner it was made with: %s", path, e)
    return changed


def rights_again(path: str) -> None:
    """The folder's right to write, once more, for something Kiboto made and handed over already:
    a copied folder gets its source's rights at the end of the copy, and loses this with them."""
    try:
        now = stat.S_IMODE(os.lstat(path).st_mode)
        want = _rights(stat.S_IMODE(os.stat(os.path.dirname(os.path.abspath(path))).st_mode), now)
        if want != now:
            os.chmod(path, want)
    except OSError as e:
        logger.debug("[Files] %s keeps the rights it was made with: %s", path, e)


def _ids(user: str, group: str) -> tuple[int, int]:
    """The numbers of a user and a group by name. The file server's container looks the names up
    itself; the usual numbers (nobody 65534, users 100) are the same there and here."""
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError:
        uid = 65534
    try:
        gid = grp.getgrnam(group).gr_gid
    except KeyError:
        gid = 100
    return uid, gid


def to_people(folder: str, user: str = "nobody", group: str = "users", mode: int = 0o775) -> bool:
    """A shared folder Kiboto made is root's, and its file server writes as the share's forced
    user: nothing could be written to it over the network. The folder itself (not what is in it)
    goes to that user and group, while it is still root's and closed to others. A folder someone
    gave another owner, or opened to everyone, is left as it is. True when it was handed over."""
    try:
        st = os.stat(folder)
    except OSError:
        return False
    if _me() != 0 or st.st_uid != 0 or not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o002:
        return False
    uid, gid = _ids(user, group)
    try:
        os.chown(folder, uid, gid)
        os.chmod(folder, mode)
    except OSError as e:
        logger.warning("[Files] the shared folder %s stays the system's: %s", folder, e)
        return False
    logger.info("[Files] the shared folder %s now belongs to %s:%s, as its file server writes", folder, user, group)
    return True


def to_person(folder: str, uid: int, gid: int = 100, mode: int = 0o700) -> bool:
    """A person's private folder on Kiboto's own file server goes to their own account. Handed
    over while it is root's or still the file server's user's (how private folders were written
    before each person had an account); a folder someone gave another owner is left as it is.
    What is inside is not changed: it stays readable and writable through the group. True when
    it was handed over."""
    try:
        st = os.stat(folder)
    except OSError:
        return False
    file_server_uid, _ = _ids("nobody", "users")
    if _me() != 0 or not stat.S_ISDIR(st.st_mode) or st.st_uid not in (0, file_server_uid, uid):
        return False
    if (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)) == (uid, gid, mode):
        return False
    try:
        os.chown(folder, uid, gid)
        os.chmod(folder, mode)
    except OSError as e:
        logger.warning("[Files] the private folder %s keeps its owner: %s", folder, e)
        return False
    return True


def for_helper(folder: str, ours: bool) -> dict[str, int]:
    """How a helper program that makes files in shared folders is started (rclone's WebDAV and
    SFTP servers), as arguments for subprocess.Popen: its umask, and as root its group. It stays
    root, because it reads Kiboto's own data to check a sign-in; what it makes is root's, with the
    shared folders' group and their right to write, so their people can change it.

    `ours`: Kiboto's own file server writes the shared folders as nobody:users, so the group is
    "users" and it may write. Elsewhere (Unraid) the folder that is served says both."""
    if ours:
        how = {"umask": 0o002, "group": _ids("nobody", "users")[1]}
    else:
        try:
            st = os.stat(folder)
        except OSError:
            return {"umask": 0o022}
        how = {"umask": 0o022 & ~stat.S_IMODE(st.st_mode), "group": st.st_gid}
    if _me() != 0:
        how.pop("group")  # only root may choose a group
    return how


def _hand(path: str, uid: int, gid: int) -> None:
    try:
        os.lchown(path, uid, gid)
    except OSError as e:
        logger.debug("[Files] %s keeps the owner it was made with: %s", path, e)


def like_source(src: str, dst: str) -> None:
    """A restored copy keeps the owner it had: `dst`, which Kiboto copied from `src`, gets the
    owner and group of `src`, and so does everything in it. Copying keeps rights and dates, and
    as root it makes root the owner."""
    if _me() != 0:
        return
    try:
        st = os.lstat(src)
    except OSError:
        return
    _hand(dst, st.st_uid, st.st_gid)
    if not stat.S_ISLNK(st.st_mode):
        try:
            os.chmod(dst, stat.S_IMODE(st.st_mode))  # and its rights, where the copy was first made like its folder
        except OSError as e:
            logger.debug("[Files] %s keeps the rights it was made with: %s", dst, e)
    if not stat.S_ISDIR(st.st_mode):
        return
    for at, dirs, files in os.walk(src):
        there = os.path.join(dst, os.path.relpath(at, src))
        for name in dirs + files:
            try:
                had = os.lstat(os.path.join(at, name))
            except OSError:
                continue
            _hand(os.path.join(there, name), had.st_uid, had.st_gid)


def like_before(path: str, before: os.stat_result | None) -> None:
    """A file put back over itself keeps the owner it had (`before`: what it was a moment ago);
    one that was not there is like the folder it is in."""
    if before is None:
        like_folder(path)
    elif _me() == 0:
        _hand(path, before.st_uid, before.st_gid)


def give_back(top: str, keep_out: Callable[[str, list[str]], object] | None = None) -> dict[str, int]:
    """Hands what is still root's in the folder `top` to the folder's people: files and folders
    Kiboto made before it did this itself, or that a tool running as root left there. Each takes
    the owner and group of the folder it is in and that folder's right to write, from the top
    down, `top` itself first. What belongs to anyone else is left alone, and links are not
    followed. `keep_out(folder, names)` may take folders out of the walk (the protected ones).
    Returns how many were looked at and how many were handed over."""
    seen = given = 0
    if _me() != 0:
        return {"seen": 0, "given": 0}
    given += like_folder(top)
    for at, dirs, files in os.walk(top):
        if keep_out is not None:
            keep_out(at, dirs)
        for name in dirs + files:
            seen += 1
            given += like_folder(os.path.join(at, name))
    return {"seen": seen, "given": given}


def below(top: str, path: str, done: set[str] | None = None) -> None:
    """`path` was just made somewhere below the folder `top`, perhaps with folders made on the
    way: each of those, from the top down, and then `path`. `done` remembers folders already
    seen to, for a caller that makes many files in a row."""
    top, path = os.path.abspath(top), os.path.abspath(path)
    rest = os.path.relpath(path, top)
    if rest == "." or rest.startswith(".."):
        return
    at = top
    parts = rest.split(os.sep)
    for part in parts[:-1]:
        at = os.path.join(at, part)
        if done is not None:
            if at in done:
                continue
            done.add(at)
        like_folder(at)
    like_folder(path)


def make_dirs(path: str) -> None:
    """os.makedirs(path, exist_ok=True); each folder that had to be made is like the one it is in."""
    path = os.path.abspath(path)
    there = path
    while not os.path.isdir(there) and os.path.dirname(there) != there:
        there = os.path.dirname(there)
    os.makedirs(path, exist_ok=True)
    if there != path:
        below(there, path)
