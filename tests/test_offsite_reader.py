"""Off-site backups on Kiboto OS: restic reads every file of the backup's folders through the root
service, which builds the command itself and only from folders in the storage folder."""

import os
import types
from pathlib import Path

import pytest

from backend import door
from backend.services import offsite_backup as ob
from backend.services import offsite_reader as rd


@pytest.fixture
def box(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    (storage / "tank" / "family").mkdir(parents=True)
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "usb").write_text("the-key\n")
    monkeypatch.setattr(rd, "POOL_PATH", str(storage))
    monkeypatch.setattr(rd, "ENV_DIR", str(tmp_path / "run-env"))
    monkeypatch.setattr(rd, "RUN_DIR", str(tmp_path / "out"))
    repo = {"id": "usb", "location": "/mnt/disks/HOLIDAY/kiboto-backup", "paths": [str(storage / "tank" / "family")]}
    monkeypatch.setattr(ob, "get_repo", lambda repo_id: dict(repo))
    monkeypatch.setattr(ob, "_key_file", lambda repo_id: str(keys / repo_id))
    monkeypatch.setattr(ob, "host_id", lambda: "host-1234abcd")
    import pwd

    me = types.SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    monkeypatch.setattr(pwd, "getpwnam", lambda name: me)
    return types.SimpleNamespace(storage=storage, keys=keys, repo=repo, tmp=tmp_path)


def test_the_root_service_builds_the_command_with_one_extra_right(box):
    seen = {}

    def run(cmd, timeout=0):
        seen["cmd"] = cmd
        env_file = next(c.split("=", 1)[1] for c in cmd if c.startswith("EnvironmentFile="))
        seen["env"] = Path(env_file).read_text()
        return 0, ""

    assert ob.read_here("usb", run=run) == {"done": True}
    cmd = seen["cmd"]
    assert cmd[:2] == ["systemd-run", "--wait"] and "AmbientCapabilities=CAP_DAC_READ_SEARCH" in cmd
    assert "CapabilityBoundingSet=CAP_DAC_READ_SEARCH" in cmd and "NoNewPrivileges=yes" in cmd and "User=kiboto" in cmd
    assert cmd[-3:] == ["--exclude", ".RecycleBin", str(box.storage / "tank" / "family")]
    assert (
        "RESTIC_PASSWORD=the-key" in seen["env"] and "RESTIC_REPOSITORY=/mnt/disks/HOLIDAY/kiboto-backup" in seen["env"]
    )
    assert not os.listdir(rd.ENV_DIR)  # the key does not stay on the machine's run folder


@pytest.mark.parametrize(
    "paths",
    [["/etc"], ["relative/folder"], [], ["/nowhere/at/all"], "not a list"],
)
def test_only_folders_in_the_storage_folder_are_read(box, paths):
    box.repo["paths"] = paths
    with pytest.raises(ValueError, match="Not reading"):
        ob.read_here("usb", run=lambda cmd, timeout=0: (0, ""))


def test_a_link_out_of_the_storage_folder_is_refused(box):
    (box.storage / "tank" / "sneaky").symlink_to("/etc")
    box.repo["paths"] = [str(box.storage / "tank" / "sneaky")]
    with pytest.raises(ValueError):
        ob.read_here("usb", run=lambda cmd, timeout=0: (0, ""))


def test_a_key_that_is_a_link_or_not_kibotos_is_refused(box, monkeypatch):
    os.remove(box.keys / "usb")
    (box.keys / "usb").symlink_to("/etc/hostname")
    with pytest.raises(OSError):
        ob.read_here("usb", run=lambda cmd, timeout=0: (0, ""))
    os.remove(box.keys / "usb")
    (box.keys / "usb").write_text("k")
    import pwd

    monkeypatch.setattr(pwd, "getpwnam", lambda name: types.SimpleNamespace(pw_uid=os.getuid() + 1, pw_gid=0))
    with pytest.raises(ValueError, match="Kiboto's own file"):
        ob.read_here("usb", run=lambda cmd, timeout=0: (0, ""))


def test_rclone_locations_and_line_breaks_stay_with_kiboto(box):
    box.repo["location"] = "rclone:cloud:backup"
    with pytest.raises(ValueError, match="rclone"):
        ob.read_here("usb", run=lambda cmd, timeout=0: (0, ""))
    with pytest.raises(ValueError, match="line break"):
        rd._env_text({"A": "one\ntwo"})


def test_a_service_that_did_not_start_is_logged(box, caplog):
    ob.read_here("usb", run=lambda cmd, timeout=0: (1, "Failed to start transient service unit"))
    assert "did not start" in caplog.text


def test_stop_asks_systemd_for_this_backup_only():
    seen = []
    assert rd.stop_here("usb", run=lambda cmd, timeout=0: seen.append(cmd) or (0, "")) is True
    assert seen == [["systemctl", "stop", "kiboto-offsite-read-usb", "kiboto-offsite-restore-usb"]]
    with pytest.raises(ValueError):
        rd.stop_here("../etc", run=lambda cmd, timeout=0: (0, ""))


def _on_os(monkeypatch):
    from backend import runtime

    monkeypatch.setattr(runtime, "without_root", lambda: True)
    monkeypatch.setattr(door, "available", lambda sock=None: True)


def test_the_web_process_follows_restics_output_and_reads_its_code(box, monkeypatch):
    _on_os(monkeypatch)
    asked = []

    def call(op, timeout=None, **args):
        asked.append((op, args))
        if op == "offsite.read":
            base = rd.out_base(args["repo_id"])
            with open(base + ".out", "a") as f:
                f.write(
                    '{"message_type":"status","percent_done":0.5}\n{"message_type":"summary","snapshot_id":"abc"}\n'
                )
            Path(base + ".code").write_text("3\n")
            Path(base + ".err").write_text("could not read one file\n")
        return {"done": True}

    monkeypatch.setattr(door, "call", call)
    lines, running = [], {}
    code, out, err = rd.run(box.repo, lines.append, running)
    assert code == 3 and "summary" in out and "status" not in out and err.startswith("could not read")
    assert len(lines) == 2 and running == {}
    rd._Running("usb").terminate()
    assert asked[-1] == ("offsite.stop_read", {"repo_id": "usb"})


def test_without_a_root_service_or_for_a_refused_backup_kiboto_runs_it_itself(box, monkeypatch):
    from backend import runtime

    monkeypatch.setattr(runtime, "without_root", lambda: False)
    with pytest.raises(rd.NotHere):
        rd.run(box.repo, print, {})
    _on_os(monkeypatch)

    def refused(op, timeout=None, **args):
        raise door.DoorError("Not reading: a folder of this backup is not in the storage folder.", kind="value")

    monkeypatch.setattr(door, "call", refused)
    with pytest.raises(rd.NotHere):
        rd.run(box.repo, print, {})

    def broken(op, timeout=None, **args):
        raise door.DoorError("the door stopped")

    monkeypatch.setattr(door, "call", broken)
    with pytest.raises(door.DoorError):
        rd.run(box.repo, print, {})


def test_a_stop_that_fails_is_logged(monkeypatch, caplog):
    def broken(op, timeout=None, **args):
        raise OSError("no door")

    monkeypatch.setattr(door, "call", broken)
    rd._Running("usb").terminate()
    assert "could not be stopped" in caplog.text


def test_the_backup_takes_the_root_service_or_its_own_restic(monkeypatch):
    repo = {"id": "usb", "location": "/x", "paths": ["/y"]}
    monkeypatch.setattr(rd, "run", lambda r, line, running: (3, "out", ""))
    assert ob._read_all(repo, ["backup"], print) == (3, "out")
    monkeypatch.setattr(rd, "run", lambda r, line, running: (12, "", "Fatal: wrong password"))
    with pytest.raises(ob.ResticError, match="wrong password"):
        ob._read_all(repo, ["backup"], print)

    def here(r, line, running):
        raise rd.NotHere("rclone locations are backed up by Kiboto itself")

    monkeypatch.setattr(rd, "run", here)
    monkeypatch.setattr(ob, "_run", lambda repo, args, **kw: (0, "own restic"))
    assert ob._read_all(repo, ["backup"], print) == (0, "own restic")

    def gone(r, line, running):
        raise OSError("door socket gone")

    monkeypatch.setattr(rd, "run", gone)
    with pytest.raises(ob.ResticError, match="could not be started"):
        ob._read_all(repo, ["backup"], print)


def test_the_door_has_the_reading_operations():
    from backend.services import host_door

    assert host_door.OPERATIONS["offsite.read"].args == {"repo_id": (str,)}
    assert host_door.OPERATIONS["offsite.stop_read"].args == {"repo_id": (str,)}
    assert door.LONG["offsite.read"] > rd.LIMIT_SECS


def _restore(box, target, run, in_storage=None):
    inside = in_storage or (lambda p: p.startswith(str(box.storage)))
    return rd.restore_with(
        "usb",
        box.repo,
        {"RESTIC_REPOSITORY": box.repo["location"], "RESTIC_CACHE_DIR": "/c"},
        str(box.keys / "usb"),
        ("abc123", "/tank/family/note.txt", target),
        inside,
        run=run,
    )


def test_a_restore_keeps_owners_on_a_machine_read_only_but_for_its_folder(box):
    seen = {}

    def run(cmd, timeout=0):
        seen["cmd"] = cmd
        env_file = next(c.split("=", 1)[1] for c in cmd if c.startswith("EnvironmentFile="))
        seen["env"] = Path(env_file).read_text()
        return 0, ""

    target = str(box.storage / "media" / "restored")
    assert _restore(box, target, run) == {"done": True}
    cmd = seen["cmd"]
    assert "ProtectSystem=strict" in cmd and f"ReadWritePaths={target} {rd.RUN_DIR}" in cmd
    assert f"CapabilityBoundingSet={rd.RESTORE_CAPS}" in cmd and "User=kiboto" not in " ".join(cmd)
    assert cmd[-9:] == [
        "--no-lock",
        "--no-cache",
        "restore",
        "--json",
        "abc123",
        "--target",
        target,
        "--include",
        "/tank/family/note.txt",
    ]
    assert "RESTIC_CACHE_DIR" not in seen["env"] and "RESTIC_PASSWORD=the-key" in seen["env"]
    assert os.path.isdir(target) and not os.listdir(rd.ENV_DIR)


def test_a_restore_goes_only_into_a_real_folder_on_the_storage(box):
    never = lambda cmd, timeout=0: pytest.fail("restic must not run")  # noqa: E731
    with pytest.raises(ValueError, match="on the storage"):
        _restore(box, "/etc/restored", never)
    (box.storage / "media").mkdir()
    (box.storage / "media" / "out").symlink_to("/etc")
    with pytest.raises(ValueError, match="on the storage"):
        _restore(box, str(box.storage / "media" / "out" / "x"), never)
    box.repo["location"] = "rclone:cloud:x"
    with pytest.raises(ValueError, match="Kiboto restores"):
        _restore(box, str(box.storage / "media" / "ok"), never)


def test_a_restore_that_did_not_start_is_logged_and_stop_stops_both(box, caplog):
    _restore(box, str(box.storage / "media" / "r2"), lambda cmd, timeout=0: (1, "Failed to start"))
    assert "did not start" in caplog.text
    seen = []
    rd.stop_here("usb", run=lambda cmd, timeout=0: seen.append(cmd) or (0, ""))
    assert seen == [["systemctl", "stop", "kiboto-offsite-read-usb", "kiboto-offsite-restore-usb"]]


def test_the_restore_takes_the_root_service_or_its_own_restic(monkeypatch, tmp_path):
    repo = {"id": "usb", "location": "/x", "paths": ["/y"]}
    args = ["restore", "--json", "abc123", "--target", str(tmp_path / "t"), "--include", "/a/b"]
    asked = {}

    def through(r, line, running, op="offsite.read", **kw):
        asked.update(op=op, **kw)
        return 0, "", ""

    monkeypatch.setattr(rd, "run", through)
    ob._restore_all(repo, args, str(tmp_path / "t"), None)
    assert asked == {"op": "offsite.restore", "snapshot_id": "abc123", "path": "/a/b", "target": str(tmp_path / "t")}
    monkeypatch.setattr(rd, "run", lambda *a, **k: (1, "", "Fatal: no matching ID found"))
    with pytest.raises(ob.ResticError, match="no matching"):
        ob._restore_all(repo, args, str(tmp_path / "t"), None)

    def here(*a, **k):
        raise rd.NotHere("rclone")

    ran = []
    monkeypatch.setattr(rd, "run", here)
    monkeypatch.setattr(ob, "_run", lambda repo, args, **kw: ran.append(args) or (0, ""))
    ob._restore_all(repo, args, str(tmp_path / "t"), None)
    assert ran == [args] and os.path.isdir(tmp_path / "t")

    def gone(*a, **k):
        raise OSError("no door")

    monkeypatch.setattr(rd, "run", gone)
    with pytest.raises(ob.ResticError, match="could not be started"):
        ob._restore_all(repo, args, str(tmp_path / "t"), None)


def test_the_door_restores_only_after_the_usual_checks(monkeypatch):
    from backend.services import host_door

    assert host_door.OPERATIONS["offsite.restore"].args == {
        "repo_id": (str,),
        "snapshot_id": (str,),
        "path": (str,),
        "target": (str,),
    }
    monkeypatch.setattr(ob, "get_repo", lambda repo_id: {"id": repo_id, "location": "/x", "paths": []})
    with pytest.raises(ValueError, match="version"):
        ob.restore_here("usb", "not-a-version; rm", "/a", "/mnt/storage/x")
