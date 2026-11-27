"""The ransomware guard never writes its guard file through a link of its name."""

import os

from backend.services import ransomware_guard as rg


def _guard(tmp_path, monkeypatch):
    g = rg.RansomwareGuard.__new__(rg.RansomwareGuard)
    g.state = {}
    g._lock = __import__("threading").Lock()
    g._save = lambda: None
    g._canary_bytes = lambda: b"guard"
    monkeypatch.setattr(rg.owned, "like_folder", lambda path: False)
    return g


def test_a_guard_file_is_made_where_there_is_none(tmp_path, monkeypatch):
    g = _guard(tmp_path, monkeypatch)
    assert g.place_canaries([str(tmp_path)]) == 1
    assert (tmp_path / rg.CANARY_NAME).read_bytes() == b"guard"


def test_a_dangling_link_of_its_name_is_not_written_through(tmp_path, monkeypatch):
    g = _guard(tmp_path, monkeypatch)
    share = tmp_path / "share"
    share.mkdir()
    target = tmp_path / "etc" / "planted"
    target.parent.mkdir()
    os.symlink(target, share / rg.CANARY_NAME)
    assert g.place_canaries([str(share)]) == 0
    assert not target.exists()
    assert g.state["canary_files"] == {}


def test_a_link_to_a_file_is_not_taken_as_the_guard_file(tmp_path, monkeypatch):
    g = _guard(tmp_path, monkeypatch)
    share = tmp_path / "share"
    share.mkdir()
    other = tmp_path / "secret.txt"
    other.write_text("keep")
    os.symlink(other, share / rg.CANARY_NAME)
    assert g.place_canaries([str(share)]) == 0
    assert other.read_text() == "keep"


def test_an_existing_guard_file_is_kept(tmp_path, monkeypatch):
    g = _guard(tmp_path, monkeypatch)
    (tmp_path / rg.CANARY_NAME).write_bytes(b"earlier")
    assert g.place_canaries([str(tmp_path)]) == 1
    assert (tmp_path / rg.CANARY_NAME).read_bytes() == b"earlier"
