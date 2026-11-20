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

import os
import stat

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
