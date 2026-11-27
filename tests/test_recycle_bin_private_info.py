"""A Recycle Bin item's .trashinfo names the deleted item and where it was: only Kiboto reads it."""

import os
import stat

from backend.services import recycle_bin


def test_the_index_file_is_kibotos_only(tmp_path, monkeypatch):
    monkeypatch.setattr(recycle_bin, "auto_empty", lambda d: None)
    share = tmp_path / "share"
    share.mkdir()
    victim = share / "diary.txt"
    victim.write_text("private")
    name = recycle_bin.move_to_bin(str(victim), str(share / ".RecycleBin"))
    info = share / ".RecycleBin" / "info" / f"{name}.trashinfo"
    assert stat.S_IMODE(os.stat(info).st_mode) == 0o600
    assert "Path=" + str(victim) in info.read_text()
