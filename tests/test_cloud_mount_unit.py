"""A cloud drive mounted on Kiboto OS runs as a unit of its own: as the host door's child it ended
with every restart of the door (each update) and left a dead mount behind."""

import subprocess

import pytest

from backend.services import rclone_engine as re_


@pytest.fixture
def engine(tmp_path, monkeypatch):
    eng = re_.RcloneEngine.__new__(re_.RcloneEngine)
    re_.RcloneEngine.__init__(eng)
    eng.remotes_dir = str(tmp_path / "remotes")
    eng.cache_dir = str(tmp_path / "cache")
    eng.config_file = str(tmp_path / "rclone.conf")
    (tmp_path / "cache").mkdir()
    monkeypatch.setattr(re_, "_through_door", lambda: False)
    monkeypatch.setattr(re_, "ensure_fuse_device", lambda: None)
    monkeypatch.setattr(eng, "_check_is_mounted", lambda name, path: False)
    monkeypatch.setattr(eng, "_get_rclone_bin", lambda: "/usr/bin/rclone")
    monkeypatch.setattr(re_, "_as_unit", lambda: True)
    ran = []

    def run(cmd, timeout, **kw):
        ran.append(list(cmd))
        code = eng.answer if cmd[0] == "systemd-run" else 0
        return subprocess.CompletedProcess(cmd, code, "", "unit failed" if code else "")

    eng.answer = 0
    monkeypatch.setattr(re_, "run_bounded", run)
    eng.ran = ran
    return eng


def test_the_mount_runs_as_its_own_unit(engine):
    res = engine.mount_remote("box", "photos", "writes", True)
    assert res["status"] == "mounted" and res["unit"] == "kiboto-cloud-box"
    start = engine.ran[-1]
    assert start[:5] == ["systemd-run", "--quiet", "--collect", "--unit", "kiboto-cloud-box"]
    assert "Type=notify" in start and start[
        start.index("/usr/bin/rclone") + 1 : start.index("/usr/bin/rclone") + 3
    ] == [
        "mount",
        "box:photos",
    ]
    assert "--read-only" in start and engine.ran[0] == ["systemctl", "stop", "kiboto-cloud-box"]
    engine.unmount_remote("box")
    assert ["systemctl", "stop", "kiboto-cloud-box"] in engine.ran[2:]


def test_a_mount_that_fails_says_why_and_leaves_no_folder(engine, tmp_path):
    engine.answer = 1
    with pytest.raises(RuntimeError, match="unit failed"):
        engine.mount_remote("box")
    assert not (tmp_path / "remotes" / "box").exists()
    (tmp_path / "cache" / "rclone_mount_box.log").write_text("couldn't connect: no route to host\n")
    with pytest.raises(RuntimeError, match="no route to host"):
        engine.mount_remote("box")


def test_a_unit_only_as_root_where_systemd_runs(monkeypatch):
    monkeypatch.setattr(re_.os, "geteuid", lambda: 1000)
    assert re_._as_unit() is False
