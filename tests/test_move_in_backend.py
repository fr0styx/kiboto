"""Re-audit R5: what "Bring your files over" needs from the copy engine: a folder listing that
works, and the number of files a copy (or a dry run) moves."""

import json
import shutil
import subprocess
import time

import pytest

from backend.services import rclone_engine


def _engine(tmp_path):
    eng = rclone_engine.RcloneEngine.__new__(rclone_engine.RcloneEngine)
    eng.config_file = str(tmp_path / "rclone.conf")
    eng._sync_jobs = {}
    eng._get_rclone_bin = lambda: "rclone"
    return eng


def test_the_listing_asks_rclone_for_json_and_puts_folders_first(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        out = json.dumps(
            [
                {"Path": "readme.txt", "Name": "readme.txt", "IsDir": False, "Size": 3},
                {"Path": "video", "Name": "video", "IsDir": True, "Size": -1},
                {"Path": "Photos", "Name": "Photos", "IsDir": True, "Size": -1},
            ]
        )
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    items = _engine(tmp_path).list_remote_files("oldnas", "")
    assert seen["cmd"][:3] == ["rclone", "lsjson", "oldnas:"]  # `lsf --json` is no rclone command
    assert "--no-modtime" in seen["cmd"] and "--json" not in seen["cmd"]
    assert [i["Path"] for i in items] == ["Photos", "video", "readme.txt"]


def test_a_listing_that_fails_or_is_not_json(tmp_path, monkeypatch):
    eng = _engine(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "logon failure"))
    with pytest.raises(RuntimeError, match="logon failure"):
        eng.list_remote_files("oldnas", "Photos")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "not json", ""))
    assert eng.list_remote_files("oldnas", "Photos") == []


@pytest.mark.skipif(shutil.which("rclone") is None, reason="rclone is not installed here")
def test_a_dry_run_counts_the_files_it_would_copy_and_the_copy_then_leaves_none(tmp_path, monkeypatch):
    src, dst = tmp_path / "old", tmp_path / "new"
    (src / "sub").mkdir(parents=True)
    dst.mkdir()
    (src / "a.txt").write_text("hello")
    (src / "sub" / "b.txt").write_text("hi")
    (dst / "a.txt").write_text("hello")
    shutil.copystat(src / "a.txt", dst / "a.txt")  # already here: same size and date
    eng = _engine(tmp_path)
    (tmp_path / "rclone.conf").write_text("")
    monkeypatch.setattr(rclone_engine, "_tell_sync_done", lambda *a, **k: None)

    def run(dry):
        job = eng.start_sync_job(str(src), str(dst), action="copy", dry_run=dry, notify=False)
        deadline = time.time() + 30
        while job["status"] == "running" and time.time() < deadline:
            time.sleep(0.05)
        assert job["status"] == "success", job
        return job

    would = run(True)
    assert would["total_files"] == 1 and would["total_bytes"] == 2
    assert not (dst / "sub").exists()  # a dry run writes nothing
    done = run(False)
    assert done["files_transferred"] == 1 and (dst / "sub" / "b.txt").read_text() == "hi"
    assert run(True)["total_files"] == 0  # the check after the copy: nothing left
