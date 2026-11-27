"""What Kiboto makes for a person belongs to the folder it is made in: its owner and group, and
the folder's right to write. Kiboto runs as root, so without this a file uploaded in the Files app
could not be changed over the network share."""

import os
import struct
import types

import pytest

from backend import owned


def _as(st, uid, gid):
    return os.stat_result((*st[:4], uid, gid, *st[6:]))


@pytest.fixture
def as_root(monkeypatch):
    """Whoever runs the test: what it makes counts as made by root, every folder as nobody:users'
    (99:100, as on Unraid), and what would be handed over is noted instead of done."""
    given = []
    real_stat, real_lstat = os.stat, os.lstat
    monkeypatch.setattr(owned, "_me", lambda: 0)
    monkeypatch.setattr(owned.os, "lstat", lambda path, *a, **k: _as(real_lstat(path, *a, **k), 0, 0))
    monkeypatch.setattr(owned.os, "stat", lambda path, *a, **k: _as(real_stat(path, *a, **k), 99, 100))
    monkeypatch.setattr(owned, "_give", lambda path, uid, gid, expect=None: given.append((path, uid, gid)))
    return given


def _mode(path):
    return oct(os.stat(path).st_mode & 0o7777)


def test_the_right_to_write_follows_the_folder():
    assert oct(owned._rights(0o777, 0o644)) == "0o666"  # a shared folder on Unraid
    assert oct(owned._rights(0o777, 0o755)) == "0o777"
    assert oct(owned._rights(0o775, 0o644)) == "0o664" and oct(owned._rights(0o775, 0o755)) == "0o775"
    assert oct(owned._rights(0o755, 0o644)) == "0o644"  # nothing to add
    assert oct(owned._rights(0o777, 0o600)) == "0o600"  # who may not read here may not write either
    assert oct(owned._rights(0o700, 0o644)) == "0o644"  # rights are never taken away


def test_a_new_file_and_folder_take_the_folders_owner_and_its_right_to_write(tmp_path, as_root):
    share = tmp_path / "Films"
    share.mkdir()
    os.chmod(share, 0o2777)
    made = share / "a.mkv"
    made.write_text("a")
    os.chmod(made, 0o644)
    assert owned.like_folder(str(made)) is True and _mode(made) == "0o666"
    assert as_root == [(str(made), 99, 100)]  # made by root, handed to the folder's owner
    sub = share / "2019"
    sub.mkdir()
    os.chmod(sub, 0o755)
    assert owned.like_folder(str(sub)) is True and _mode(sub) in ("0o777", "0o2777")
    assert owned.like_folder(str(share / "missing")) is False


def test_a_filesystem_without_owners_refuses_and_that_is_not_an_error(tmp_path, as_root, monkeypatch):
    share = tmp_path / "usb"
    share.mkdir()
    made = share / "a.mkv"
    made.write_text("a")

    def refuses(path, uid, gid, expect=None):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(owned, "_give", refuses)
    assert owned.like_folder(str(made)) is False


def test_a_file_of_someone_elses_is_never_touched(tmp_path, monkeypatch):
    share = tmp_path / "Films"
    share.mkdir()
    os.chmod(share, 0o777)
    theirs = share / "theirs.txt"
    theirs.write_text("x")
    os.chmod(theirs, 0o600)
    monkeypatch.setattr(owned, "_me", lambda: os.lstat(theirs).st_uid + 1)  # Kiboto is another user than its owner
    given = []
    monkeypatch.setattr(owned, "_give", lambda *a: given.append(a))
    assert owned.like_folder(str(theirs)) is False and given == [] and _mode(theirs) == "0o600"


def test_a_link_is_handed_over_and_not_followed(tmp_path, as_root):
    share = tmp_path / "Films"
    share.mkdir()
    os.chmod(share, 0o777)
    target = tmp_path / "outside.txt"
    target.write_text("x")
    os.chmod(target, 0o600)
    link = share / "link"
    os.symlink(target, link)
    owned.like_folder(str(link))
    assert _mode(target) == "0o600"  # what the link points at keeps its rights


def test_folders_made_on_the_way_are_seen_to_from_the_top_down(tmp_path, monkeypatch):
    monkeypatch.setattr(owned, "_me", lambda: os.lstat(tmp_path).st_uid)  # the test's files are Kiboto's own
    monkeypatch.setattr(owned, "_give", lambda *a: None)
    share = tmp_path / "Films"
    share.mkdir()
    os.chmod(share, 0o775)
    old_umask = os.umask(0o022)
    try:
        owned.make_dirs(str(share / "2019" / "summer"))
        assert _mode(share / "2019") == "0o775" and _mode(share / "2019" / "summer") == "0o775"
        owned.make_dirs(str(share / "2019" / "summer"))  # there already: nothing happens
        os.chmod(share / "2019", 0o700)
        owned.make_dirs(str(share / "2019" / "winter"))
        assert _mode(share / "2019") == "0o700"  # a folder that was there keeps what it has
        deep = share / "a" / "b" / "c.txt"
        os.makedirs(deep.parent)
        deep.write_text("c")
        done: set[str] = set()
        owned.below(str(share), str(deep), done)
        assert (_mode(share / "a"), _mode(share / "a" / "b"), _mode(deep)) == ("0o775", "0o775", "0o664")
        assert done == {str(share / "a"), str(share / "a" / "b")}
        assert owned.like_folder(str(deep)) is False  # nothing left to change
        os.chmod(share / "a", 0o755)
        owned.below(str(share), str(deep), done)
        assert _mode(share / "a") == "0o755"  # seen to once in a run of many files
        os.chmod(share / "a" / "b", 0o755)  # a copied folder got its source's rights back
        owned.rights_again(str(share / "a" / "b"))
        assert _mode(share / "a" / "b") == "0o755"  # the folder above gives no right to write: none added
        os.chmod(share / "a", 0o775)
        owned.rights_again(str(share / "a" / "b"))
        assert _mode(share / "a" / "b") == "0o775"
        owned.rights_again(str(share / "a" / "missing"))  # gone: nothing happens
        owned.below(str(share), str(share))  # the top itself, or a path outside it: nothing
        owned.below(str(share), str(tmp_path / "elsewhere"))
    finally:
        os.umask(old_umask)


def test_a_restored_copy_keeps_the_owners_it_had(tmp_path, monkeypatch):
    src, dst = tmp_path / "snapshot" / "album", tmp_path / "live" / "album"
    (src / "deep").mkdir(parents=True)
    (src / "one.txt").write_text("1")
    (src / "deep" / "two.txt").write_text("2")
    (dst / "deep").mkdir(parents=True)
    (dst / "one.txt").write_text("1")  # two.txt is missing in the copy: skipped without a word
    owners = {"album": (1000, 100), "one.txt": (1001, 100), "deep": (1002, 100), "two.txt": (1003, 100)}
    real, given = os.lstat, []

    def lstat(path, *a, **k):
        return _as(real(path, *a, **k), *owners[os.path.basename(str(path))])

    def lchown(path, uid, gid, expect=None):
        if not os.path.lexists(path):
            raise FileNotFoundError(2, "No such file", path)
        given.append((os.path.relpath(path, tmp_path / "live"), uid, gid))

    monkeypatch.setattr(owned.os, "lstat", lstat)
    monkeypatch.setattr(owned, "_give", lchown)
    monkeypatch.setattr(owned, "_me", lambda: 1000)
    owned.like_source(str(src), str(dst))
    assert given == []  # only root can hand a file to someone
    monkeypatch.setattr(owned, "_me", lambda: 0)
    owned.like_source(str(src), str(dst))
    assert sorted(given) == [("album", 1000, 100), ("album/deep", 1002, 100), ("album/one.txt", 1001, 100)]
    given.clear()
    os.chmod(src / "one.txt", 0o640)
    os.chmod(dst / "one.txt", 0o666)  # the copy was first made like its folder
    owned.like_source(str(src / "one.txt"), str(dst / "one.txt"))  # one file
    assert given == [("album/one.txt", 1001, 100)] and _mode(dst / "one.txt") == "0o640"
    monkeypatch.setattr(owned.os, "lstat", real)
    owned.like_source(str(tmp_path / "gone"), str(dst))  # no source: nothing happens
    assert len(given) == 1


def test_a_file_put_back_over_itself_keeps_its_owner(tmp_path, as_root):
    share = tmp_path / "Films"
    share.mkdir()
    put_back = share / "a.txt"
    put_back.write_text("a")
    owned.like_before(str(put_back), _as(os.lstat(put_back), 1005, 100))
    assert as_root == [(str(put_back), 1005, 100)]
    as_root.clear()
    owned.like_before(str(put_back), None)  # it was not there: like the folder it is in
    assert as_root == [(str(put_back), 99, 100)]


def test_a_shared_folder_goes_to_the_file_servers_user(tmp_path, monkeypatch):
    share = tmp_path / "Films"
    share.mkdir()
    os.chmod(share, 0o755)
    given = []
    real = os.stat
    owner = {"uid": 0}
    monkeypatch.setattr(owned.os, "stat", lambda path, *a, **k: _as(real(path, *a, **k), owner["uid"], 0))
    monkeypatch.setattr(owned, "_give", lambda path, uid, gid, expect=None: given.append((path, uid, gid)))
    monkeypatch.setattr(owned, "_ids", lambda user, group: (65534, 100))
    monkeypatch.setattr(owned, "_me", lambda: 1000)
    assert owned.to_people(str(share)) is False and given == []  # only root can hand a folder over
    monkeypatch.setattr(owned, "_me", lambda: 0)
    assert owned.to_people(str(share)) is True
    assert given == [(str(share), 65534, 100)] and _mode(share) == "0o775"
    os.chmod(share, 0o755)
    assert owned.to_people(str(share), mode=0o770) is True and _mode(share) == "0o770"  # a private folder
    given.clear()
    # left as they are: a folder someone gave another owner, one open to everyone, a file, a missing one
    os.chmod(share, 0o755)
    owner["uid"] = 1000
    assert owned.to_people(str(share)) is False
    owner["uid"] = 0
    os.chmod(share, 0o777)
    assert owned.to_people(str(share)) is False
    a_file = tmp_path / "a.txt"
    a_file.write_text("a")
    assert owned.to_people(str(a_file)) is False and owned.to_people(str(tmp_path / "missing")) is False
    assert given == []

    def refuses(path, uid, gid, expect=None):
        raise PermissionError(1, "Operation not permitted")

    os.chmod(share, 0o755)
    monkeypatch.setattr(owned, "_give", refuses)
    assert owned.to_people(str(share)) is False and _mode(share) == "0o755"


def test_the_numbers_of_a_user_and_a_group():
    uid, gid = owned._ids("root", "root")
    assert (uid, gid) == (0, 0)
    assert owned._ids("no-such-user-here", "no-such-group-here") == (65534, 100)  # the usual nobody and users


def test_how_a_helper_that_makes_files_is_started(tmp_path, monkeypatch):
    pool = tmp_path / "pool"
    pool.mkdir()
    os.chmod(pool, 0o777)
    real = os.stat
    monkeypatch.setattr(owned.os, "stat", lambda path, *a, **k: _as(real(path, *a, **k), 99, 100))
    monkeypatch.setattr(owned, "_ids", lambda user, group: (65534, 100))
    monkeypatch.setattr(owned, "_me", lambda: 0)
    # Unraid: the folder that is served says the group and the right to write
    assert owned.for_helper(str(pool), ours=False) == {"umask": 0o000, "group": 100}
    os.chmod(pool, 0o755)
    assert owned.for_helper(str(pool), ours=False) == {"umask": 0o022, "group": 100}
    assert owned.for_helper(str(tmp_path / "missing"), ours=False) == {"umask": 0o022}
    # Kiboto's own file server: the shared folders are nobody:users, written by the group
    assert owned.for_helper(str(pool), ours=True) == {"umask": 0o002, "group": 100}
    # only root may choose a group
    monkeypatch.setattr(owned, "_me", lambda: 1000)
    assert owned.for_helper(str(pool), ours=True) == {"umask": 0o002}
    assert owned.for_helper(str(pool), ours=False) == {"umask": 0o022}


def test_what_is_still_the_systems_in_a_folder_goes_to_its_people(tmp_path, monkeypatch):
    share = tmp_path / "Films"
    (share / "old" / "deep").mkdir(parents=True)
    (share / "old" / "a.mkv").write_text("a")
    (share / "old" / "deep" / "b.mkv").write_text("b")
    (share / "theirs.txt").write_text("t")
    (share / "apps" / "db").mkdir(parents=True)
    os.symlink(tmp_path, share / "link")
    owner = {str(share): 99, str(share / "theirs.txt"): 1001}  # everything else was made by root
    real_stat, real_lstat = os.stat, os.lstat
    given = []

    def uid_of(path):
        return owner.get(str(path), 0)

    def lchown(path, uid, gid, expect=None):
        owner[str(path)] = uid
        given.append(os.path.relpath(path, share))

    monkeypatch.setattr(owned.os, "lstat", lambda p, *a, **k: _as(real_lstat(p, *a, **k), uid_of(p), 100))
    monkeypatch.setattr(owned.os, "stat", lambda p, *a, **k: _as(real_stat(p, *a, **k), uid_of(p), 100))
    monkeypatch.setattr(owned, "_give", lchown)
    monkeypatch.setattr(owned, "_me", lambda: 1000)
    assert owned.give_back(str(share)) == {"seen": 0, "given": 0}  # only root can hand anything over
    monkeypatch.setattr(owned, "_me", lambda: 0)

    def keep_out(folder, names):
        if "apps" in names:
            names.remove("apps")  # a protected folder: not entered

    out = owned.give_back(str(share), keep_out)
    # each from the top down, so a folder is its people's before what is in it is looked at
    # (the order inside one folder is the disk's own, and differs from machine to machine)
    assert sorted(given) == ["link", "old", "old/a.mkv", "old/deep", "old/deep/b.mkv"]
    assert given.index("old") < given.index("old/a.mkv") and given.index("old") < given.index("old/deep")
    assert given.index("old/deep") < given.index("old/deep/b.mkv")
    assert out == {"seen": 6, "given": 5}  # theirs.txt was seen and left alone; apps was not entered
    assert "theirs.txt" not in given and not [g for g in given if g.startswith("apps")]
    assert owned.give_back(str(share), keep_out)["given"] == 0  # nothing left to hand over


def test_a_folder_the_web_user_made_is_handed_over_by_the_door(tmp_path, monkeypatch):
    """Once Kiboto's web process is the user kiboto (ADR 0006 step 9), the door hands over what
    that user made: a new person's home, a new shared folder."""
    home = tmp_path / "ana"
    home.mkdir()
    os.chmod(home, 0o755)
    given = []
    real = os.stat
    monkeypatch.setattr(owned.os, "stat", lambda path, *a, **k: _as(real(path, *a, **k), 999, 999))
    monkeypatch.setattr(owned, "_give", lambda path, uid, gid, expect=None: given.append((path, uid, gid)))
    monkeypatch.setattr(owned, "_ids", lambda user, group: (65534, 100))
    monkeypatch.setattr(owned, "_me", lambda: 0)
    monkeypatch.setattr(owned, "_ours", lambda: {0, 999})
    assert owned.to_person(str(home), 20001) is True and given[-1] == (str(home), 20001, 100)
    assert owned.to_people(str(home)) is True and given[-1] == (str(home), 65534, 100)
    monkeypatch.setattr(owned, "_ours", lambda: {0})  # someone else's folder: left alone
    os.chmod(home, 0o755)
    assert owned.to_people(str(home)) is False


def test_rights_are_never_changed_through_a_link_swapped_in_after_the_look(tmp_path, monkeypatch):
    """On Kiboto OS root sets rights in shared folders that people write to over the network: a file
    swapped for a link to a system file after it was looked at must not change that file."""
    share = tmp_path / "Films"
    share.mkdir()
    os.chmod(share, 0o777)
    made = share / "a.mkv"
    made.write_text("a")
    os.chmod(made, 0o600)
    system = tmp_path / "shadow"
    system.write_text("root only")
    os.chmod(system, 0o600)
    monkeypatch.setattr(owned, "_me", lambda: os.lstat(made).st_uid)
    real, swapped = os.lstat, []

    def look_then_swap(path, *a, **k):
        st = real(path, *a, **k)
        if str(path) == str(made) and not swapped:
            swapped.append(1)
            os.rename(made, share / "a.old")
            os.symlink(system, made)
        return st

    monkeypatch.setattr(owned.os, "lstat", look_then_swap)
    assert owned.like_folder(str(made)) is False
    assert _mode(system) == "0o600"  # the system file keeps its rights


def test_nothing_is_changed_through_a_folder_on_the_way_that_is_a_link(tmp_path, monkeypatch):
    share = tmp_path / "Films"
    share.mkdir()
    elsewhere = tmp_path / "etc"
    elsewhere.mkdir()
    (elsewhere / "passwd").write_text("x")
    os.chmod(elsewhere / "passwd", 0o600)
    (share / "sub").symlink_to(elsewhere)
    with pytest.raises(OSError):
        owned._mode(str(share / "sub" / "passwd"), 0o666)
    with pytest.raises(OSError):
        owned._give(str(share / "sub" / "passwd"), os.getuid(), os.getgid())
    assert _mode(elsewhere / "passwd") == "0o600"


def test_the_change_helpers_set_rights_and_owner_on_the_file_itself(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("a")
    os.chmod(f, 0o600)
    owned._mode(str(f), 0o664, os.lstat(f))
    assert _mode(f) == "0o664"
    owned._give(str(f), os.getuid(), os.getgid(), os.lstat(f))  # to its own owner: allowed to anyone
    other = tmp_path / "b.txt"
    other.write_text("b")
    with pytest.raises(OSError):
        owned._mode(str(f), 0o600, os.lstat(other))  # not the file that was looked at
    os.mkfifo(tmp_path / "pipe")
    owned._mode(str(tmp_path / "pipe"), 0o666)  # a pipe is never opened: nothing happens


def _acl(*entries):
    """A system.posix_acl_access value: version 2, then (tag, perm, id) entries."""
    import struct

    return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", tag, perm, uid) for tag, perm, uid in entries)


USER_OBJ, USER, GROUP_OBJ, GROUP, MASK, OTHER = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20


def test_a_private_folder_keeps_the_grants_it_names_and_shuts_everyone_else_out():
    inherited = _acl((USER_OBJ, 7, 0), (USER, 7, 999), (GROUP_OBJ, 5, 0), (GROUP, 5, 100), (MASK, 7, 0), (OTHER, 5, 0))
    assert owned.private_acl(inherited) == _acl(
        (USER_OBJ, 7, 0), (USER, 7, 999), (GROUP_OBJ, 0, 0), (GROUP, 0, 100), (MASK, 7, 0), (OTHER, 0, 0)
    )
    cut = _acl((USER_OBJ, 7, 0), (USER, 7, 999), (GROUP_OBJ, 5, 0), (MASK, 0, 0), (OTHER, 0, 0))  # made private by 700
    assert owned.private_acl(cut) == _acl(
        (USER_OBJ, 7, 0), (USER, 7, 999), (GROUP_OBJ, 0, 0), (MASK, 7, 0), (OTHER, 0, 0)
    )
    assert (
        owned.private_acl(_acl((USER_OBJ, 7, 0), (GROUP_OBJ, 5, 0), (OTHER, 5, 0))) is None
    )  # names nobody: 700 does it
    assert owned.private_acl(b"\x02\x00") is None
    no_mask = owned.private_acl(_acl((USER_OBJ, 7, 0), (USER, 7, 999), (GROUP_OBJ, 5, 0), (OTHER, 5, 0)))
    assert no_mask.endswith(_acl((MASK, 7, 0xFFFFFFFF))[4:])


def test_handing_a_home_over_writes_the_private_list_or_the_mode(tmp_path, monkeypatch):
    home = tmp_path / "anna"
    home.mkdir()
    os.chmod(home, 0o700)
    inherited = _acl((USER_OBJ, 7, 0), (USER, 7, 999), (GROUP_OBJ, 5, 0), (MASK, 7, 0), (OTHER, 5, 0))
    written, modes = [], []
    monkeypatch.setattr(owned, "_through_door", lambda: False)
    monkeypatch.setattr(owned, "_ids", lambda user, group: (65534, 100))
    monkeypatch.setattr(owned, "_me", lambda: 0)
    monkeypatch.setattr(owned, "_ours", lambda: {os.getuid()})
    monkeypatch.setattr(owned, "_give", lambda path, uid, gid, st=None: None)
    monkeypatch.setattr(owned, "_mode", lambda path, mode, st=None: modes.append(mode))
    monkeypatch.setattr(owned.os, "getxattr", lambda p, attr, follow_symlinks=True: inherited)
    monkeypatch.setattr(owned.os, "setxattr", lambda fd, attr, value: written.append(value))
    assert owned.to_person(str(home), os.getuid(), os.getgid()) is True
    assert (
        written == [owned.private_acl(inherited, os.getuid())] * 2 and modes == []
    )  # the folder, and what is made in it

    def none(*a, **k):
        raise OSError(61, "No data available")

    monkeypatch.setattr(owned.os, "getxattr", none)
    assert owned.to_person(str(home), os.getuid(), os.getgid() + 1) is True and modes == [0o700]


def test_a_folder_kiboto_made_as_a_dataset_lets_kibotos_user_in():
    """A new ZFS dataset or btrfs subvolume takes no access list from the folder it is in: a home made
    as one was shut to the page (403). The grant is added to the list, or to the one the mode stands for."""
    plain = owned.with_grant(b"", 0o750, 999)
    assert plain == _acl(
        (USER_OBJ, 7, 0xFFFFFFFF),
        (USER, 7, 999),
        (GROUP_OBJ, 5, 0xFFFFFFFF),
        (MASK, 7, 0xFFFFFFFF),
        (OTHER, 0, 0xFFFFFFFF),
    )
    existing = _acl(
        (USER_OBJ, 7, 0xFFFFFFFF),
        (USER, 5, 1001),
        (GROUP_OBJ, 0, 0xFFFFFFFF),
        (MASK, 0, 0xFFFFFFFF),
        (OTHER, 0, 0xFFFFFFFF),
    )
    assert owned.with_grant(existing, 0o700, 999) == _acl(
        (USER_OBJ, 7, 0xFFFFFFFF),
        (USER, 7, 999),
        (USER, 5, 1001),
        (GROUP_OBJ, 0, 0xFFFFFFFF),
        (MASK, 7, 0xFFFFFFFF),
        (OTHER, 0, 0xFFFFFFFF),
    )


def test_granting_writes_both_lists_and_skips_a_machine_without_that_user(tmp_path, monkeypatch):
    import pwd

    folder = tmp_path / "homes"
    folder.mkdir()
    written = []
    monkeypatch.setattr(pwd, "getpwnam", lambda name: types.SimpleNamespace(pw_uid=999))
    monkeypatch.setattr(owned.os, "getxattr", lambda fd, attr: (_ for _ in ()).throw(OSError(61, "No data")))
    monkeypatch.setattr(owned.os, "setxattr", lambda fd, attr, value: written.append(attr))
    assert owned.grant_web_user(str(folder)) is True
    assert written == [owned.ACL_XATTR, owned.ACL_DEFAULT_XATTR]

    def nobody(name):
        raise KeyError(name)

    monkeypatch.setattr(pwd, "getpwnam", nobody)
    assert owned.grant_web_user(str(folder)) is False


def test_the_person_is_named_in_their_own_folder_so_what_kibotos_user_makes_there_stays_theirs():
    """On Kiboto OS rclone writes SFTP uploads as Kiboto's own user: in a home whose list named
    only that user, the person could not open their own upload over SMB."""
    kiboto_only = _acl((USER_OBJ, 7, 0), (USER, 7, 999), (GROUP_OBJ, 0, 0), (MASK, 7, 0), (OTHER, 0, 0))
    assert owned.private_acl(kiboto_only, 20001) == _acl(
        (USER_OBJ, 7, 0xFFFFFFFF),
        (USER, 7, 999),
        (USER, 7, 20001),
        (GROUP_OBJ, 0, 0xFFFFFFFF),
        (MASK, 7, 0xFFFFFFFF),
        (OTHER, 0, 0xFFFFFFFF),
    )
    named = owned.private_acl(kiboto_only, 20001)
    assert owned.private_acl(named, 20001) == named  # settled: written once
    assert owned.private_acl(_acl((USER_OBJ, 7, 0), (GROUP_OBJ, 5, 0), (OTHER, 5, 0)), 20001) is None  # 700 does it


def _acl(*entries):
    return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *e) for e in entries)


ANY = 0xFFFFFFFF
# a folder made inside one whose default access list gave the group r-x, Kiboto's own user named
INHERITED = _acl((0x01, 7, ANY), (0x02, 7, 999), (0x04, 5, ANY), (0x10, 7, ANY), (0x20, 5, ANY))


def test_the_group_entry_follows_the_mode():
    fixed = owned.group_entry(INHERITED, 7)
    assert fixed == _acl((0x01, 7, ANY), (0x02, 7, 999), (0x04, 7, ANY), (0x10, 7, ANY), (0x20, 5, ANY))
    shut = _acl((0x01, 7, ANY), (0x04, 0, ANY), (0x10, 0, ANY), (0x20, 0, ANY))
    assert owned.group_entry(shut, 5) == _acl((0x01, 7, ANY), (0x04, 5, ANY), (0x10, 5, ANY), (0x20, 0, ANY))
    assert owned.group_entry(b"\x02\x00", 7) is None


def test_a_shared_folders_group_may_write_whatever_its_access_list_said(tmp_path, monkeypatch):
    """A guest over SMB is let in through the share's group: a share folder whose inherited access
    list kept the group at r-x refused every guest write, though its mode showed rwx."""
    share = tmp_path / "Guests"
    share.mkdir()
    os.chmod(share, 0o755)
    lists = {owned.ACL_XATTR: INHERITED, owned.ACL_DEFAULT_XATTR: INHERITED}
    written = {}
    monkeypatch.setattr(owned.os, "getxattr", lambda fd, attr: lists[attr])
    monkeypatch.setattr(owned.os, "setxattr", lambda fd, attr, raw: written.__setitem__(attr, raw))
    real = os.stat
    owner = {"uid": 0, "gid": 0}
    monkeypatch.setattr(owned.os, "stat", lambda path, *a, **k: _as(real(path, *a, **k), owner["uid"], owner["gid"]))
    monkeypatch.setattr(owned, "_give", lambda path, uid, gid, expect=None: owner.update(uid=uid, gid=gid))
    monkeypatch.setattr(owned, "_ids", lambda user, group: (65534, 100))
    monkeypatch.setattr(owned, "_me", lambda: 0)
    assert owned.to_people(str(share)) is True
    group_rwx = owned.group_entry(INHERITED, 7)
    assert written == {owned.ACL_XATTR: group_rwx, owned.ACL_DEFAULT_XATTR: group_rwx}
    # one handed over before this was known: put right when the file server's settings are written
    written.clear()
    assert owned.to_people(str(share)) is False
    assert written == {owned.ACL_XATTR: group_rwx, owned.ACL_DEFAULT_XATTR: group_rwx}
    lists.update({owned.ACL_XATTR: group_rwx, owned.ACL_DEFAULT_XATTR: group_rwx})
    written.clear()
    assert owned.to_people(str(share)) is False and written == {}  # nothing to change: nothing written

    def no_list(fd, attr):
        raise OSError(61, "No data available")

    monkeypatch.setattr(owned.os, "getxattr", no_list)
    assert owned.to_people(str(share)) is False and written == {}  # no access list: the mode is all

    def refused(fd, attr, raw):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(owned.os, "getxattr", lambda fd, attr: INHERITED)
    monkeypatch.setattr(owned.os, "setxattr", refused)
    assert owned.to_people(str(share)) is False  # said in the log, nothing raised
