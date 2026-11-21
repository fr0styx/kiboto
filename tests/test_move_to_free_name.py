"""fsutil.move_to_free_name: a finished file goes to the first free name, never over another."""

import os

import pytest

from backend import fsutil


def test_first_free_name_and_a_claim_taken_meanwhile(tmp_path):
    (tmp_path / "a").write_text("first")
    (tmp_path / "b").write_text("second")
    (tmp_path / "c").write_text("third")
    assert fsutil.move_to_free_name(str(tmp_path / "a"), str(tmp_path), "scan.pdf") == str(tmp_path / "scan.pdf")
    assert fsutil.move_to_free_name(str(tmp_path / "b"), str(tmp_path), "scan.pdf") == str(tmp_path / "scan (2).pdf")
    (tmp_path / "scan (3).pdf").write_text("")  # another upload claimed it a moment ago
    assert fsutil.move_to_free_name(str(tmp_path / "c"), str(tmp_path), "scan.pdf") == str(tmp_path / "scan (4).pdf")
    assert (tmp_path / "scan.pdf").read_text() == "first" and (tmp_path / "scan (2).pdf").read_text() == "second"


def test_all_names_taken_and_a_failed_move_leave_no_claim(tmp_path, monkeypatch):
    (tmp_path / "x").write_text("x")
    (tmp_path / "n.txt").write_text("there")
    assert fsutil.move_to_free_name(str(tmp_path / "x"), str(tmp_path), "n.txt", tries=1) is None
    assert (tmp_path / "x").exists()

    def no_move(src, dst):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(fsutil.os, "replace", no_move)
    with pytest.raises(OSError):
        fsutil.move_to_free_name(str(tmp_path / "x"), str(tmp_path), "new.txt")
    assert not os.path.exists(tmp_path / "new.txt")  # the claim went with the failure
