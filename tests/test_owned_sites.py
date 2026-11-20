"""Where the Files app makes things for a person, they follow the folder they are made in
(backend/owned.py). A shared folder that lets everyone write stands for one on Unraid."""

import os
import zipfile

import pytest

from backend import owned
from backend.services import fs_transfer as ft


@pytest.fixture
def share(tmp_path, monkeypatch):
    monkeypatch.setattr(owned, "_me", lambda: os.lstat(tmp_path).st_uid)  # the test's files are Kiboto's own
    monkeypatch.setattr(owned.os, "lchown", lambda *a: None)
    old = os.umask(0o022)  # as the server runs
    folder = tmp_path / "Films"
    folder.mkdir()
    os.chmod(folder, 0o777)
    yield folder
    os.umask(old)


def _mode(path):
    return oct(os.stat(path).st_mode & 0o777)


def test_a_copy_of_a_file_and_of_a_folder(share, tmp_path):
    src = tmp_path / "src"
    (src / "album" / "deep").mkdir(parents=True)
    (src / "one.txt").write_text("1")
    (src / "album" / "two.txt").write_text("2")
    (src / "album" / "deep" / "three.txt").write_text("3")
    os.chmod(src / "one.txt", 0o600)  # a file its owner alone may read stays that way
    out = ft.execute_transfer([str(src / "one.txt"), str(src / "album")], str(share), "copy", "merge")
    assert not out.get("errors"), out
    assert _mode(share / "one.txt") == "0o600"
    assert (_mode(share / "album"), _mode(share / "album" / "deep")) == ("0o777", "0o777")
    assert (_mode(share / "album" / "two.txt"), _mode(share / "album" / "deep" / "three.txt")) == ("0o666", "0o666")
    # into a folder that only its owner writes: nothing is added
    closed = tmp_path / "closed"
    closed.mkdir()
    os.chmod(closed, 0o755)
    ft.execute_transfer([str(src / "album")], str(closed), "copy", "merge")
    assert (_mode(closed / "album"), _mode(closed / "album" / "two.txt")) == ("0o755", "0o644")


def test_an_upload_that_lands(share, tmp_path):
    from backend.api.files.uploads import _land

    staged = share / ".kiboto_tmp_x"
    staged.write_text("up")
    assert _mode(staged) == "0o644"
    landed = _land(str(staged), str(share), "holiday.jpg", "keep_both", None)
    assert landed == str(share / "holiday.jpg") and _mode(landed) == "0o666"


def test_a_new_folder(share, monkeypatch):
    from backend.api.files import browse

    monkeypatch.setattr(browse, "ALLOWED_BROWSE_ROOTS", [str(share)])
    monkeypatch.setattr(browse, "_contained", lambda path, must_exist=False: path)
    assert browse._do_mkdir(str(share / "New folder"))["status"] == "ok"
    assert _mode(share / "New folder") == "0o777"


def test_what_an_archive_holds(share, tmp_path):
    packed = tmp_path / "a.zip"
    with zipfile.ZipFile(packed, "w") as z:
        z.writestr("zipped/dir/z.txt", "z")
        z.writestr("top.txt", "t")
    seen: set[str] = set()
    with zipfile.ZipFile(packed) as z:
        for info in z.infolist():
            owned.below(str(share), z.extract(info, str(share)), seen)
    assert (_mode(share / "zipped"), _mode(share / "zipped" / "dir")) == ("0o777", "0o777")
    assert (_mode(share / "zipped" / "dir" / "z.txt"), _mode(share / "top.txt")) == ("0o666", "0o666")


def test_a_file_moved_across_drives_keeps_its_owner(share, tmp_path, monkeypatch):
    """On the same drive a move is a rename and nothing changes. Across drives it is a copy, and
    the copy gets the owner and rights the file had, not the destination folder's."""
    src = tmp_path / "src.txt"
    src.write_text("m")
    os.chmod(src, 0o640)
    kept = []
    monkeypatch.setattr(owned, "like_source", lambda s, d: kept.append((s, d)))
    real = os.replace

    def other_drive(a, b):
        if a == str(src):
            raise OSError(18, "Invalid cross-device link")
        return real(a, b)

    monkeypatch.setattr(ft.os, "replace", other_drive)
    ft._move_file_resilient(str(src), str(share / "moved.txt"))
    assert kept == [(str(src), str(share / "moved.txt"))]
    assert not src.exists() and (share / "moved.txt").read_text() == "m"
