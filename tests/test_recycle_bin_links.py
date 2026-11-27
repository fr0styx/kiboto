"""A Recycle Bin reached through a link is never written to, listed or emptied."""

import os
import time

import pytest

from backend.services import recycle_bin as rb


@pytest.fixture
def share(tmp_path, monkeypatch):
    monkeypatch.setattr(rb, "_index_file", lambda: str(tmp_path / "bins.json"))
    monkeypatch.setattr(rb, "asleep", lambda recycle_dir: False)
    root = tmp_path / "storage"
    (root / "docs").mkdir(parents=True)
    monkeypatch.setattr(rb.config, "ALLOWED_BROWSE_ROOTS", [str(root)])
    return root / "docs"


def _outside(tmp_path):
    out = tmp_path / "system"
    (out / "files").mkdir(parents=True)
    old = out / "old-file"
    old.write_text("system")
    long_ago = time.time() - 400 * 86400
    os.utime(old, (long_ago, long_ago))
    return out


def test_a_plain_bin_is_used(share):
    (share / "a.txt").write_text("a")
    name = rb.move_to_bin(str(share / "a.txt"), str(share / rb.BIN), str(share / "a.txt"), True)
    assert name and (share / rb.BIN / "files" / name).read_text() == "a"
    assert rb.plain_bin(str(share / rb.BIN))
    assert str(share / rb.BIN) in rb.all_bins()


def test_a_bin_that_is_a_link_is_not_moved_into(share, tmp_path):
    out = _outside(tmp_path)
    os.symlink(out, share / rb.BIN)
    (share / "a.txt").write_text("a")
    with pytest.raises(OSError, match="link"):
        rb.move_to_bin(str(share / "a.txt"), str(share / rb.BIN), str(share / "a.txt"), True)
    assert (share / "a.txt").exists() and os.listdir(out / "files") == []


def test_a_files_folder_that_is_a_link_is_not_moved_into(share, tmp_path):
    out = _outside(tmp_path)
    (share / rb.BIN).mkdir()
    os.symlink(out / "files", share / rb.BIN / "files")
    (share / "a.txt").write_text("a")
    with pytest.raises(OSError, match="link"):
        rb.move_to_bin(str(share / "a.txt"), str(share / rb.BIN), str(share / "a.txt"), True)
    assert os.listdir(out / "files") == []


def test_a_bin_that_is_a_link_is_never_listed_or_emptied(share, tmp_path):
    out = _outside(tmp_path)
    os.symlink(out, share / rb.BIN)
    assert str(share / rb.BIN) not in rb.all_bins()
    assert rb.items(str(share / rb.BIN)) == []
    assert rb.auto_empty(str(share / rb.BIN), force=True) == 0
    assert (out / "old-file").read_text() == "system"
