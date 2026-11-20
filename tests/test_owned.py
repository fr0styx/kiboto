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
