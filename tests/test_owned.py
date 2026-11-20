"""What Kiboto makes for a person belongs to the folder it is made in: its owner and group, and
the folder's right to write. Kiboto runs as root, so without this a file uploaded in the Files app
could not be changed over the network share."""

import os

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
    monkeypatch.setattr(owned.os, "lchown", lambda path, uid, gid: given.append((path, uid, gid)))
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

    def refuses(path, uid, gid):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(owned.os, "lchown", refuses)
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
    monkeypatch.setattr(owned.os, "lchown", lambda *a: given.append(a))
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
    monkeypatch.setattr(owned.os, "lchown", lambda *a: None)
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

    def lchown(path, uid, gid):
        if not os.path.lexists(path):
            raise FileNotFoundError(2, "No such file", path)
        given.append((os.path.relpath(path, tmp_path / "live"), uid, gid))

    monkeypatch.setattr(owned.os, "lstat", lstat)
    monkeypatch.setattr(owned.os, "lchown", lchown)
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


def test_the_umask_for_a_helper_that_makes_files_in_a_folder(tmp_path):
    share = tmp_path / "Films"
    share.mkdir()
    for mode, want in ((0o777, 0o000), (0o775, 0o002), (0o755, 0o022), (0o700, 0o022), (0o2777, 0o000)):
        os.chmod(share, mode)
        assert owned.umask_in(str(share)) == want, oct(mode)
    assert owned.umask_in(str(tmp_path / "missing")) == 0o022


def test_a_shared_folder_goes_to_the_file_servers_user(tmp_path, monkeypatch):
    share = tmp_path / "Films"
    share.mkdir()
    os.chmod(share, 0o755)
    given = []
    real = os.stat
    owner = {"uid": 0}
    monkeypatch.setattr(owned.os, "stat", lambda path, *a, **k: _as(real(path, *a, **k), owner["uid"], 0))
    monkeypatch.setattr(owned.os, "chown", lambda path, uid, gid: given.append((path, uid, gid)))
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

    def refuses(path, uid, gid):
        raise PermissionError(1, "Operation not permitted")

    os.chmod(share, 0o755)
    monkeypatch.setattr(owned.os, "chown", refuses)
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
