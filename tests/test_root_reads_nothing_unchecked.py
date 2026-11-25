"""Nothing the root service reads may sit unchecked in the web user's folder (ADR 0006; found by the
release review, 25 Nov 2026): the network trial's record, a snapshot's file list, the door's log."""

import json
import os
import stat

import pytest

from backend import runtime
from backend.hardware.net import managed
from backend.services import data_snapshot, host_door, native_update


@pytest.fixture
def net(tmp_path, monkeypatch):
    (tmp_path / "network").mkdir()
    monkeypatch.setattr(managed, "DIR", str(tmp_path / "network"))
    monkeypatch.setattr(managed, "STATE", str(tmp_path / "data" / "network_trial.json"))
    monkeypatch.setattr(managed, "ROOT_STATE", str(tmp_path / "door" / "network_trial.json"))
    (tmp_path / "data").mkdir()
    return tmp_path


def _trial(net, **over):
    ours = os.path.join(managed.DIR, "05-kiboto-enp1s0.network")
    rec = {"id": "k", "iface": "enp1s0", "ifaces": ["enp1s0"], "files": {ours: None}, "started": 1.0, "timeout": 60}
    rec.update(over)
    return rec


def test_only_kibotos_own_network_files_are_put_back(net):
    d = managed.DIR
    assert managed.unsafe(_trial(net)) == ""
    assert managed.unsafe(_trial(net, files={f"{d}/05-kiboto-br0.netdev": "[NetDev]\n"})) == ""
    assert managed.unsafe(_trial(net, files={f"{d}/10-kiboto-enp1s0.link": "[Match]\n"})) == ""
    assert (
        managed.unsafe({"id": "k", "iface": "eth0", "path": f"{d}/05-kiboto-eth0.network", "started": 1, "timeout": 5})
        == ""
    )
    bad = [
        _trial(net, files={"/etc/cron.d/x": "* * * * * root id\n"}),
        _trial(net, files={"/etc/sudoers.d/kiboto": "kiboto ALL=(ALL) NOPASSWD: ALL\n"}),
        _trial(net, files={f"{d}/../../etc/passwd": "x"}),
        _trial(net, files={f"{d}/99-other.network": "x"}),
        _trial(net, files={f"{d}/05-kiboto-x.service": "x"}),
        _trial(net, files={f"{d}/sub/05-kiboto-x.network": "x"}),
        _trial(net, files={}),
        _trial(net, files=["/etc/passwd"]),
        _trial(net, files={f"{d}/05-kiboto-a.network": 7}),
        _trial(net, files={f"{d}/05-kiboto-a.network": "a\0b"}),
        _trial(net, ifaces=["-j", "eth0"]),
        _trial(net, ifaces=["eth0; reboot"]),
        _trial(net, ifaces="eth0"),
        _trial(net, started="soon"),
        _trial(net, timeout=True),
    ]
    for rec in bad:
        assert managed.unsafe(rec), rec


def test_a_planted_record_is_never_acted_on(net, monkeypatch):
    """The web user writes a record that names a file outside, then asks for the way back."""
    target = net / "outside.txt"
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    for where in (managed.STATE, managed.ROOT_STATE):
        os.makedirs(os.path.dirname(where), exist_ok=True)
        with open(where, "w") as f:
            json.dump(_trial(net, files={str(target): "written as root\n"}), f)
        ran = []
        assert managed.go_back(None, lambda cmd, timeout=20, ran=ran: ran.append(cmd) or (0, "")) == {
            "status": "ok",
            "reverted": False,
        }
        assert not target.exists() and ran == []
        os.remove(where)


def test_root_keeps_the_record_in_its_own_folder(net, monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    assert managed._record() == managed.ROOT_STATE
    monkeypatch.setattr(runtime, "managed_host", lambda: False)
    assert managed._record() == managed.STATE  # a container: one user, one folder
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    monkeypatch.setattr(os, "geteuid", lambda: 999)
    assert managed._record() == managed.STATE  # the web process cannot read root's folder


def test_a_record_in_the_data_folder_counts_only_when_root_wrote_it(net, monkeypatch):
    """A trial begun by the version before: its record is still in the data folder."""
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    with open(managed.STATE, "w") as f:
        json.dump(_trial(net), f)
    real = os.lstat

    def owned_by(uid):
        def lstat(path, *a, **k):
            st = real(path, *a, **k)
            if str(path) == managed.STATE:
                return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, uid, st.st_gid, *st[6:]))
            return st

        return lstat

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "lstat", owned_by(0))
    assert managed._trial()["id"] == "k"
    monkeypatch.setattr(os, "lstat", owned_by(999))
    assert managed._trial() is None


def test_the_page_asks_the_door_for_the_trial():
    assert "network.trial_status" in host_door.OPERATIONS
    assert host_door.OPERATIONS["network.trial_status"].args == {}


def test_a_snapshot_list_that_leaves_the_folder_is_refused(tmp_path):
    snap, data = tmp_path / "snap", tmp_path / "data"
    snap.mkdir()
    data.mkdir()
    (snap / "users.db").write_text("x")
    for item in ("/etc/cron.d/x", "../outside", "a/../../b", "", 7):
        (snap / "manifest.json").write_text(json.dumps({"files": ["users.db", item]}))
        with pytest.raises(ValueError, match="not a file of the data folder"):
            data_snapshot.restore_snapshot(str(snap), str(data))
        assert not (data / "users.db").exists()  # checked before anything is copied
    (snap / "manifest.json").write_text(json.dumps({"files": ["users.db"]}))
    assert data_snapshot.restore_snapshot(str(snap), str(data)) == ["users.db"]


def test_snapshots_are_taken_and_put_back_in_the_owners_name(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    ran, handed = [], []
    real_stat = os.stat

    def stat_as_web_user(path, *a, **k):
        st = real_stat(path, *a, **k)
        if str(path) == str(data):
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, 987, 987, *st[6:]))
        return st

    class Done:
        returncode, stdout, stderr = 0, "/d/backups/pre-update/20261125\n", ""

    monkeypatch.setattr(native_update.os, "geteuid", lambda: 0)
    monkeypatch.setattr(native_update.os, "stat", stat_as_web_user)
    monkeypatch.setattr(native_update, "_hand_back", lambda d: handed.append(d))
    monkeypatch.setattr(native_update.subprocess, "run", lambda cmd, **kw: ran.append((cmd, kw)) or Done())
    out = native_update._in_the_owners_name(str(data), ["take", str(data), "before-update", "{}"])
    assert out == "/d/backups/pre-update/20261125" and handed == [str(data)]
    cmd, kw = ran[0]
    assert cmd[1:] == ["-m", "backend.services.data_snapshot", "take", str(data), "before-update", "{}"]
    assert (kw["user"], kw["group"], kw["extra_groups"]) == (987, 987, [])

    class Failed:
        returncode, stdout, stderr = 1, "", "the snapshot lists '/etc/x', which is not a file of the data folder\n"

    monkeypatch.setattr(native_update.subprocess, "run", lambda cmd, **kw: Failed())
    with pytest.raises(OSError, match="not a file of the data folder"):
        native_update._in_the_owners_name(str(data), ["restore", "/s", str(data)])


def test_in_a_folder_of_roots_own_the_snapshot_is_made_here(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "users.db").write_text("x")
    monkeypatch.setattr(native_update.subprocess, "run", lambda *a, **k: pytest.fail("no other process"))
    made = native_update._in_the_owners_name(str(data), ["take", str(data), "t", json.dumps({"kind": "update"})])
    assert os.path.isfile(os.path.join(made, "manifest.json"))
    assert native_update._in_the_owners_name(str(data), ["restore", made, str(data)]) == ""


def test_the_snapshot_program_takes_and_puts_back(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    (data / "users.db").write_text("x")
    assert data_snapshot.main(["x", "take", str(data), "t", "{}"]) == 0
    made = capsys.readouterr().out.strip()
    assert data_snapshot.main(["x", "restore", made, str(data)]) == 0
    assert data_snapshot.main(["x", "restore", str(tmp_path / "none"), str(data)]) == 1
    assert data_snapshot.main(["x", "nothing"]) == 2


def test_the_doors_log_is_never_written_through_a_link(tmp_path):
    log, victim = tmp_path / "door-audit.log", tmp_path / "victim"
    victim.write_text("keep\n")
    os.symlink(victim, log)
    fd = host_door._audit_file(str(log))
    os.write(fd, b"line\n")
    os.close(fd)
    assert victim.read_text() == "keep\n" and not os.path.islink(log) and log.read_text() == "line\n"
    # a second name for another file (a hard link) is not written into either
    os.remove(log)
    os.link(victim, log)
    fd = host_door._audit_file(str(log))
    os.write(fd, b"again\n")
    os.close(fd)
    assert victim.read_text() == "keep\n" and log.read_text() == "again\n"
    assert stat.S_IMODE(os.stat(log).st_mode) == 0o644


def test_a_log_of_someone_elses_is_begun_again(tmp_path, monkeypatch):
    log = tmp_path / "door-audit.log"
    log.write_text("forged\n")
    monkeypatch.setattr(host_door.os, "geteuid", lambda: os.stat(log).st_uid + 1)  # not this service's file
    with pytest.raises(OSError):
        host_door._audit_file(str(log))  # the new file is not ours either, here: refused, not written
