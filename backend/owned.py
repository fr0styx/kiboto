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

Once Kiboto's web process no longer runs as root (ADR 0006), it cannot hand a file to anyone: the
host door does it, confined to the storage folders, and takes what the web process's user made
as Kiboto's own. While it is root it does it itself, as a door call per file would slow a copy
of many files.
"""

from __future__ import annotations

import contextlib
import errno
import grp
import os
import pwd
import stat
import struct
from collections.abc import Callable
from typing import Any

from backend.config import logger


def _me() -> int:
    return os.geteuid()


WEB_USER = "kiboto"  # the web process's user once it gives up root (services/host_door.USER)


def _ours() -> set[int]:
    """Whose files "Kiboto made": this process's, and in the door the web process's user too."""
    try:
        return {_me(), pwd.getpwnam(WEB_USER).pw_uid}
    except KeyError:  # no such user yet: the web process is root
        return {_me()}


def _through_door() -> bool:
    from backend import door

    return _me() != 0 and door.available()


def _door(op: str, **args: Any) -> Any:
    """`op` in the host door; None when it refused or could not be reached (said in the log)."""
    from backend import door

    try:
        return door.call(op, **args)
    except (OSError, door.DoorError) as e:
        logger.debug("[Files] the door did not do %s: %s", op, e)
        return None


# --- changing an owner or rights without following a link ---------------------------------------
# On Kiboto OS this runs as root in the host door, inside shared folders that people write to over
# the network. Between looking at a file and changing it, someone could put a link in its place, or
# in the place of a folder on the way to it, and have root change a system file instead. So every
# change is made by name in a folder reached from the top one folder at a time without following a
# link, after checking it is still the file that was looked at; rights are set on an open handle.
_DIR = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)


def _open_folder(folder: str) -> int:
    fd = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in [p for p in os.path.abspath(folder).split(os.sep) if p]:
            nxt = os.open(part, _DIR, dir_fd=fd)
            os.close(fd)
            fd = nxt
    except OSError:
        os.close(fd)
        raise
    return fd


@contextlib.contextmanager
def _entry(path: str, expect: os.stat_result | None):
    """The folder `path` is in (open) and its name there; refused (OSError) when a link is on the
    way or the file is no longer the one that was looked at (`expect`)."""
    parent, name = os.path.split(os.path.abspath(path))
    pfd = _open_folder(parent)
    try:
        st = os.stat(name, dir_fd=pfd, follow_symlinks=False)
        if expect is not None and (st.st_dev, st.st_ino) != (expect.st_dev, expect.st_ino):
            raise FileNotFoundError(errno.ENOENT, "replaced while it was looked at", path)
        yield pfd, name, st
    finally:
        os.close(pfd)


def _give(path: str, uid: int, gid: int, expect: os.stat_result | None = None) -> None:
    """lchown, with no link followed on the way to `path` either."""
    with _entry(path, expect) as (pfd, name, _):
        os.chown(name, uid, gid, dir_fd=pfd, follow_symlinks=False)


def _mode(path: str, mode: int, expect: os.stat_result | None = None) -> None:
    """chmod of a plain file or folder, on an open handle of it: never through a link, and never a
    device or a pipe (opening those can have effects of their own)."""
    with _entry(path, expect) as (pfd, name, st):
        if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
            return
        fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), dir_fd=pfd)
        try:
            now = os.fstat(fd)
            if (now.st_dev, now.st_ino) != (st.st_dev, st.st_ino):
                raise FileNotFoundError(errno.ENOENT, "replaced while it was opened", path)
            os.fchmod(fd, mode)
        finally:
            os.close(fd)


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
    if _through_door():
        return bool(_door("files.like_folder", path=path))
    try:
        st = os.lstat(path)
        folder = os.stat(os.path.dirname(os.path.abspath(path)))
    except OSError:
        return False
    me = _me()
    if st.st_uid not in _ours():
        return False  # not made by Kiboto: left as it is
    changed = False
    try:
        if not stat.S_ISLNK(st.st_mode):
            now, want = stat.S_IMODE(st.st_mode), _rights(stat.S_IMODE(folder.st_mode), stat.S_IMODE(st.st_mode))
            if want != now:
                _mode(path, want, st)
                changed = True
        if me == 0 and (st.st_uid, st.st_gid) != (folder.st_uid, folder.st_gid):
            _give(path, folder.st_uid, folder.st_gid, st)
            changed = True
    except OSError as e:
        logger.debug("[Files] %s keeps the owner it was made with: %s", path, e)
    return changed


def rights_again(path: str) -> None:
    """The folder's right to write, once more, for something Kiboto made and handed over already:
    a copied folder gets its source's rights at the end of the copy, and loses this with them."""
    if _through_door():
        _door("files.rights_again", path=path)
        return
    try:
        st = os.lstat(path)
        now = stat.S_IMODE(st.st_mode)
        want = _rights(stat.S_IMODE(os.stat(os.path.dirname(os.path.abspath(path))).st_mode), now)
        if want != now and not stat.S_ISLNK(st.st_mode):
            _mode(path, want, st)
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
    if _through_door():
        return bool(_door("files.to_people", folder=folder, user=user, group=group, mode=mode))
    try:
        st = os.stat(folder)
    except OSError:
        return False
    if _me() != 0 or not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o002:
        return False  # only root hands a folder over; a file, or a folder open to everyone, stays as it is
    uid, gid = _ids(user, group)
    if (st.st_uid, st.st_gid) == (uid, gid):  # handed over before: its group may still be shut out
        _group_like_mode(folder, mode, st)
        return False
    if st.st_uid not in _ours():
        return False  # made by someone else than Kiboto (root, or its web user)
    try:
        _give(folder, uid, gid, st)
        _mode(folder, mode, st)
        _group_like_mode(folder, mode, os.stat(folder))
    except OSError as e:
        logger.warning("[Files] the shared folder %s stays the system's: %s", folder, e)
        return False
    logger.info("[Files] the shared folder %s now belongs to %s:%s, as its file server writes", folder, user, group)
    return True


ACL_XATTR = "system.posix_acl_access"
ACL_DEFAULT_XATTR = "system.posix_acl_default"  # what files made inside the folder start with
_ACL_USER, _ACL_GROUP_OBJ, _ACL_GROUP, _ACL_MASK, _ACL_OTHER = 0x02, 0x04, 0x08, 0x10, 0x20


def group_entry(raw: bytes, perm: int) -> bytes | None:
    """An access list whose group entry is `perm`, its mask letting that through. None when `raw`
    is not an access list."""
    if len(raw) < 4 or (len(raw) - 4) % 8:
        return None
    out = []
    for i in range((len(raw) - 4) // 8):
        tag, now, who = struct.unpack_from("<HHI", raw, 4 + 8 * i)
        if tag == _ACL_GROUP_OBJ:
            now = perm
        elif tag == _ACL_MASK:
            now |= perm
        out.append(struct.pack("<HHI", tag, now, who))
    return raw[:4] + b"".join(out)


def _group_like_mode(folder: str, mode: int, st: os.stat_result) -> None:
    """The group's entry in a folder's access lists as `mode` says. With an access list, chmod
    moves only the mask: a share folder made inside one whose list gave the group r-x stayed shut
    to the group whatever its mode showed, and a guest over SMB (let in through the share's group,
    not as its owner) could write nothing. The default list too, so folders made in it are alike."""
    want = (mode >> 3) & 7
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    try:
        now = os.fstat(fd)
        if (now.st_dev, now.st_ino) != (st.st_dev, st.st_ino):
            return
        for attr in (ACL_XATTR, ACL_DEFAULT_XATTR):
            try:
                raw = os.getxattr(fd, attr)
            except OSError:
                continue  # no access list: the mode is all there is
            fixed = group_entry(raw, want)
            if fixed is not None and fixed != raw:
                os.setxattr(fd, attr, fixed)
    except OSError as e:
        logger.warning("[Files] the group of %s keeps its access: %s", folder, e)
    finally:
        os.close(fd)


def private_acl(raw: bytes, person: int | None = None) -> bytes | None:
    """A private folder's access list that keeps the grants it names (Kiboto's own user, on Kiboto
    OS): the group and everyone else get nothing, and the mask lets the named users in. None when
    the list names no user (then mode 700 makes the folder private, as before). A home made
    private by 700 alone had its mask cut to nothing, and the web process could not open a person's
    own folder.

    `person`: the folder's owner is named too. What Kiboto's own user makes in it (a file put over
    SFTP, which rclone writes as that user) then stays the person's to read, change and delete;
    before, they could not even open it over SMB in their own folder."""
    if len(raw) < 4 or (len(raw) - 4) % 8:
        return None
    entries = [struct.unpack_from("<HHI", raw, 4 + 8 * i) for i in range((len(raw) - 4) // 8)]
    if not any(tag == _ACL_USER for tag, _perm, _id in entries):
        return None
    out = []
    for tag, perm, uid in entries:
        if tag in (_ACL_GROUP_OBJ, _ACL_GROUP, _ACL_OTHER):
            perm = 0
        elif tag == _ACL_MASK:
            perm = 7
        out.append(struct.pack("<HHI", tag, perm, uid))
    if not any(tag == _ACL_MASK for tag, _perm, _id in entries):
        out.append(struct.pack("<HHI", _ACL_MASK, 7, 0xFFFFFFFF))
    closed = raw[:4] + b"".join(out)
    return closed if person is None else with_grant(closed, 0o700, person)


_ACL_USER_OBJ = 0x01
WEB_USER = "kiboto"  # services/web_user.USER


def with_grant(raw: bytes, mode: int, uid: int) -> bytes:
    """An access list (or the one `mode` stands for, when there is none) that also lets user `uid`
    read and write, with the mask open for it; entries in the order the kernel wants them."""
    entries: dict[tuple[int, int], int] = {}
    if len(raw) >= 4 and (len(raw) - 4) % 8 == 0:
        for i in range((len(raw) - 4) // 8):
            tag, perm, who = struct.unpack_from("<HHI", raw, 4 + 8 * i)
            entries[(tag, who if tag in (_ACL_USER, _ACL_GROUP) else 0xFFFFFFFF)] = perm
    else:
        entries = {
            (_ACL_USER_OBJ, 0xFFFFFFFF): (mode >> 6) & 7,
            (_ACL_GROUP_OBJ, 0xFFFFFFFF): (mode >> 3) & 7,
            (_ACL_OTHER, 0xFFFFFFFF): mode & 7,
        }
    entries[(_ACL_USER, uid)] = 7
    entries[(_ACL_MASK, 0xFFFFFFFF)] = 7
    body = b"".join(struct.pack("<HHI", tag, perm, who) for (tag, who), perm in sorted(entries.items()))
    return struct.pack("<I", 2) + body


def grant_web_user(folder: str) -> bool:
    """Kiboto's own user may read and write `folder`, and what is made in it: for a folder Kiboto has
    just made as a ZFS dataset or btrfs subvolume of its own (a homes folder, a person's home), which
    takes no access list from the folder it is in, so a person's own home was shut to the page (403).
    Written on an open handle, never through a link; nothing where that user does not exist."""
    try:
        uid = pwd.getpwnam(WEB_USER).pw_uid
    except KeyError:
        return False
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    try:
        mode = stat.S_IMODE(os.fstat(fd).st_mode)
        for attr in (ACL_XATTR, ACL_DEFAULT_XATTR):
            try:
                raw = os.getxattr(fd, attr)
            except OSError:
                raw = b""
            os.setxattr(fd, attr, with_grant(raw, mode, uid))
    except OSError as e:
        logger.warning("[Files] %s keeps its access list: %s", folder, e)
        return False
    finally:
        os.close(fd)
    return True


def _make_private(folder: str, mode: int, st: os.stat_result, person: int | None = None) -> None:
    """Mode `mode`, or on a folder whose access list names a user, that list made private
    (private_acl), written on an open handle of the folder: never through a link."""
    try:
        raw = os.getxattr(folder, ACL_XATTR, follow_symlinks=False) if mode == 0o700 else b""
    except OSError:
        raw = b""
    closed = private_acl(raw, person) if raw else None
    if closed is None:
        _mode(folder, mode, st)
        return
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    try:
        now = os.fstat(fd)
        if (now.st_dev, now.st_ino) != (st.st_dev, st.st_ino):
            raise FileNotFoundError(errno.ENOENT, "replaced while it was opened", folder)
        if closed != raw:
            os.setxattr(fd, ACL_XATTR, closed)
        try:  # files made inside start private too: nothing for the group or anyone else, the mask open
            inherited = os.getxattr(fd, ACL_DEFAULT_XATTR)
        except OSError:
            inherited = b""
        made_private = private_acl(inherited, person) if inherited else None
        if made_private is not None and made_private != inherited:
            os.setxattr(fd, ACL_DEFAULT_XATTR, made_private)
    finally:
        os.close(fd)


def to_person(folder: str, uid: int, gid: int = 100, mode: int = 0o700) -> bool:
    """A person's private folder on Kiboto's own file server goes to their own account. Handed
    over while it is root's or still the file server's user's (how private folders were written
    before each person had an account); a folder someone gave another owner is left as it is.
    What is inside is not changed: it stays readable and writable through the group. True when
    it was handed over."""
    if _through_door():
        return bool(_door("files.to_person", folder=folder, uid=uid, gid=gid, mode=mode))
    try:
        st = os.stat(folder)
    except OSError:
        return False
    file_server_uid, _ = _ids("nobody", "users")
    if _me() != 0 or not stat.S_ISDIR(st.st_mode) or st.st_uid not in {file_server_uid, uid} | _ours():
        return False
    try:
        raw = os.getxattr(folder, ACL_XATTR, follow_symlinks=False)
    except OSError:
        raw = b""
    try:
        inherited = os.getxattr(folder, ACL_DEFAULT_XATTR, follow_symlinks=False)
    except OSError:
        inherited = b""
    settled = (
        raw
        and private_acl(raw, uid) == raw
        and stat.S_IMODE(st.st_mode) == 0o770
        and (not inherited or private_acl(inherited, uid) in (None, inherited))
    )
    if (st.st_uid, st.st_gid) == (uid, gid) and (settled or (not raw and stat.S_IMODE(st.st_mode) == mode)):
        return False
    try:
        _give(folder, uid, gid, st)
        _make_private(folder, mode, st, uid)
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
        _give(path, uid, gid)
    except OSError as e:
        logger.debug("[Files] %s keeps the owner it was made with: %s", path, e)


def like_source(src: str, dst: str) -> None:
    """A restored copy keeps the owner it had: `dst`, which Kiboto copied from `src`, gets the
    owner and group of `src`, and so does everything in it. Copying keeps rights and dates, and
    as root it makes root the owner."""
    if _through_door():
        _door("files.like_source", src=src, dst=dst)
        return
    if _me() != 0:
        return
    try:
        st = os.lstat(src)
    except OSError:
        return
    _hand(dst, st.st_uid, st.st_gid)
    if not stat.S_ISLNK(st.st_mode):
        try:
            _mode(dst, stat.S_IMODE(st.st_mode))  # and its rights, where the copy was first made like its folder
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
    elif _through_door():
        _door("files.hand_back", path=path, uid=before.st_uid, gid=before.st_gid)
    elif _me() == 0:
        _hand(path, before.st_uid, before.st_gid)


def give_back(top: str, keep_out: Callable[[str, list[str]], object] | None = None) -> dict[str, int]:
    """Hands what is still root's in the folder `top` to the folder's people: files and folders
    Kiboto made before it did this itself, or that a tool running as root left there. Each takes
    the owner and group of the folder it is in and that folder's right to write, from the top
    down, `top` itself first. What belongs to anyone else is left alone, and links are not
    followed. `keep_out(folder, names)` may take folders out of the walk (the protected ones).
    Returns how many were looked at and how many were handed over. Through the door, the
    protected folders are always kept out (fsutil.prune_protected)."""
    if _through_door():
        got = _door("files.give_back", top=top)
        return got if isinstance(got, dict) else {"seen": 0, "given": 0}
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
