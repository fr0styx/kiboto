"""Bringing the settings back from the copy on the pools, after the machine was set up again."""

import json
import os

import pytest

from backend import config, machine_key, runtime
from backend.hardware.pal import pool_probe, pool_registry
from backend.services import backup_engine, host_basics, pool_copy

OLD_KEY = "o" * 64
THEIRS = "feedfacefeedface"


def a_copy(root, name="attic", install=THEIRS, at=1000.0, recovery=None, sub=""):
    folder = os.path.join(root, ".kiboto", sub)
    os.makedirs(folder)
    with open(os.path.join(folder, "about.json"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "install": install, "name": name, "version": "2.0.5", "at": at, "pool": "x"}, f)
    with open(os.path.join(folder, "settings.kbak"), "wb") as f:
        f.write(b"ZETTBAK2 the archive of " + name.encode())
    with open(os.path.join(folder, "data-key.recovery"), "w", encoding="utf-8") as f:
        json.dump(machine_key.wrap(OLD_KEY, recovery) if recovery else {"v": 1}, f)


@pytest.fixture
def box(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    monkeypatch.setattr(machine_key, "DIR", str(tmp_path / "keys"))
    monkeypatch.setattr(machine_key, "_stretched", lambda key, salt: (key.encode() + salt + b"0" * 32)[:32])
    monkeypatch.setattr(pool_copy, "FOUND", str(tmp_path / "found"))
    (tmp_path / "pools" / "tank").mkdir(parents=True)
    rows = [{"name": "tank", "mountpoint": str(tmp_path / "pools" / "tank"), "members": []}]
    monkeypatch.setattr(pool_registry, "load", lambda: rows)
    monkeypatch.setattr(os.path, "ismount", lambda p: os.path.isdir(p) and "pools" in p)
    made = type("Box", (), {"root": tmp_path, "candidates": [], "roots": {}})()
    monkeypatch.setattr(pool_probe, "candidates", lambda run: made.candidates)
    monkeypatch.setattr(pool_probe, "look_into", lambda c, run, read: read(made.roots[c["name"]]))
    return made


def unused(box, pool, **copy):
    root = box.root / "unused" / pool
    root.mkdir(parents=True)
    box.candidates.append({"kind": "ext4", "name": pool, "id": pool})
    box.roots[pool] = str(root)
    if copy:
        a_copy(str(root), **copy)
    return root


def test_a_guest_looks_nowhere(tmp_path, monkeypatch):
    monkeypatch.setattr(pool_copy, "FOUND", str(tmp_path / "found"))
    assert pool_copy.look(run=lambda cmd: pytest.fail("no command on a guest")) == []
    assert pool_copy.found() == []


def test_looking_finds_other_installs_copies_on_pools_in_use_and_not(box):
    a_copy(
        str(box.root / "pools" / "tank"), name="mine", install=pool_copy.install_id()
    )  # this install's own: not offered
    a_copy(str(box.root / "pools" / "tank"), name="older", at=500.0, sub=f"earlier/{THEIRS}")
    unused(box, "media", name="attic", install="0123456789abcdef", at=2000.0)
    unused(box, "empty")
    got = pool_copy.look(run=lambda cmd: (0, "", ""))
    assert [(c["name"], c["pool"], c["key"]) for c in got] == [
        ("attic", "media", "0123456789abcdef-media"),  # newest first
        ("older", "tank", f"{THEIRS}-tank"),
    ]
    assert got == pool_copy.found()
    assert sorted(os.listdir(box.root / "found" / "0123456789abcdef-media")) == [
        "about.json",
        "data-key.recovery",
        "settings.kbak",
    ]
    assert "pool" in got[0] and "version" in got[0] and got[0]["at"] == 2000.0


def test_a_look_replaces_what_the_look_before_found(box):
    root = unused(box, "media", name="attic")
    assert len(pool_copy.look(run=lambda cmd: (0, "", ""))) == 1
    import shutil

    shutil.rmtree(root / ".kiboto")
    assert pool_copy.look(run=lambda cmd: (0, "", "")) == [] and pool_copy.found() == []


def test_half_a_copy_and_a_note_with_odd_text_are_handled(box):
    root = unused(box, "media", name="at\x00tic\n<b>" + "x" * 200, install="FEED-face/../..")
    os.remove(root / ".kiboto" / "data-key.recovery")
    assert pool_copy.look(run=lambda cmd: (0, "", "")) == []  # an archive without its key is no copy
    (root / ".kiboto" / "data-key.recovery").write_text("{}")
    got = pool_copy.look(run=lambda cmd: (0, "", ""))[0]
    assert got["key"] == "feedface-media" and "\x00" not in got["name"] and len(got["name"]) == 64
    (box.root / "found" / "junk").mkdir()
    (box.root / "found" / "junk" / "about.json").write_text('{"key": "other"}')
    assert [c["key"] for c in pool_copy.found()] == ["feedface-media"]


def test_a_candidate_that_cannot_be_read_does_not_stop_the_look(box, monkeypatch):
    unused(box, "media", name="attic")
    unused(box, "broken")

    def look_into(c, run, read):
        if c["name"] == "broken":
            raise OSError("Input/output error")
        return read(box.roots[c["name"]])

    monkeypatch.setattr(pool_probe, "look_into", look_into)
    assert [c["pool"] for c in pool_copy.look(run=lambda cmd: (0, "", ""))] == ["media"]


@pytest.fixture
def restorable(box, monkeypatch, tmp_path):
    recovery = machine_key.new_recovery_key()
    unused(box, "media", name="attic", recovery=recovery)
    pool_copy.look(run=lambda cmd: (0, "", ""))
    calls = {}

    def restore_archive(f, passphrase="", snapshot=True, staged=False):
        calls["archive"] = (f.read(), passphrase, snapshot, staged)
        return {"restored": 38, "staged": True}

    monkeypatch.setattr(backup_engine, "restore_backup_archive", restore_archive)
    from backend.services import data_snapshot

    monkeypatch.setattr(
        data_snapshot, "take_snapshot", lambda d, label="", extra=None: calls.__setitem__("snapshot", label) or "/snap"
    )
    monkeypatch.setattr(
        machine_key, "adopt", lambda key, wrapped, do=None: calls.__setitem__("adopt", (key, wrapped)) or "chip"
    )
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(pool_copy, "DATA_DIR", str(data))
    monkeypatch.setattr(config, "initial_password_file", lambda: str(data / "initial-admin-password"))
    for name in ("initial-admin-password", "rag_index.db", "rag_index.db-wal", "users.db"):
        (data / name).write_text("x")
    return recovery, calls, data


def test_the_recovery_key_of_the_install_that_wrote_it_brings_the_settings_back(restorable):
    recovery, calls, data = restorable
    done = pool_copy.restore(f"{THEIRS}-media", recovery.lower().replace("-", " "))
    assert done == {"restored": 38, "name": "attic", "pool": "media"}
    blob, passphrase, snapshot, staged = calls["archive"]
    assert blob == b"ZETTBAK2 the archive of attic" and passphrase == pool_copy.passphrase(OLD_KEY)
    assert snapshot is False and staged is True  # nothing open is written over
    assert calls["snapshot"] == "pre-restore"  # today's settings were saved first, under this machine's key
    assert calls["adopt"][0] == OLD_KEY and machine_key.unwrap(calls["adopt"][1], recovery) == OLD_KEY
    assert sorted(os.listdir(data)) == [".adopt-restored-pools", "rag_index.db", "rag_index.db-wal", "users.db"]
    # the index goes at the next start: the running Kiboto may still write to it until then
    assert pool_copy.drop_index_after_restore(str(data)) is True
    assert sorted(os.listdir(data)) == [".adopt-restored-pools", "users.db"]
    assert pool_copy.drop_index_after_restore(str(data / "elsewhere")) is False


@pytest.mark.parametrize("key", ["", "nope", "../../etc/passwd", "feedfacefeedface-other", "FEEDFACEFEEDFACE-media"])
def test_a_copy_that_is_not_at_hand_is_refused(restorable, key):
    with pytest.raises(ValueError, match="no longer at hand"):
        pool_copy.restore(key, restorable[0])
    assert "archive" not in restorable[1]


@pytest.mark.parametrize("typed", ["", "not a key", "AAAA-AAAA-AAAA-AAAA-AAAA-AAAA"])
def test_a_wrong_recovery_key_changes_nothing(restorable, typed):
    _recovery, calls, data = restorable
    with pytest.raises(ValueError, match="not this machine's recovery key"):
        pool_copy.restore(f"{THEIRS}-media", typed)
    assert calls == {} and ".adopt-restored-pools" not in os.listdir(data)
    assert pool_copy.drop_index_after_restore(str(data)) is False and "rag_index.db" in os.listdir(data)


def test_an_archive_that_does_not_restore_leaves_this_machines_key_alone(restorable, monkeypatch):
    recovery, calls, data = restorable

    def broken(f, **kwargs):
        raise ValueError("Backup archive exceeds maximum allowable file count (1000)")

    monkeypatch.setattr(backup_engine, "restore_backup_archive", broken)
    with pytest.raises(ValueError, match="maximum allowable file count"):
        pool_copy.restore(f"{THEIRS}-media", recovery)
    assert "adopt" not in calls and "initial-admin-password" in os.listdir(data)


def test_the_machine_takes_the_restored_installs_key_and_its_recovery_key(box, tmp_path):
    seen = []

    def do(cmd, feed=None, timeout=60):
        seen.append((cmd, feed))
        if cmd[:2] == ["systemd-creds", "encrypt"]:
            with open(cmd[-1], "w", encoding="utf-8") as f:
                f.write("sealed")
        return 0, "", ""

    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / machine_key.SHOWN).write_text("NEWM-ACHI-NESK-EYNO-TNEE-DED2")
    recovery = machine_key.new_recovery_key()
    wrapped = machine_key.wrap(OLD_KEY, recovery)
    assert machine_key.adopt(OLD_KEY, wrapped, do=do) == "chip"
    assert sorted(os.listdir(keys)) == [
        "data-key.cred",
        "data-key.recovery",
        "state.json",
    ]  # nothing left to write down
    assert json.loads((keys / "data-key.recovery").read_text()) == wrapped
    assert [feed for cmd, feed in seen if cmd[:2] == ["systemd-creds", "encrypt"]] == [OLD_KEY]
    assert machine_key._state()["written_down_at"] > 0


def test_restored_zfs_pools_are_taken_from_the_system_that_is_gone_once(tmp_path, monkeypatch):
    monkeypatch.setattr(pool_registry, "DATA_DIR", str(tmp_path))
    rows = [{"name": "tank", "fs_type": "zfs", "uuid": "42", "mountpoint": "/mnt/storage/tank"}]
    monkeypatch.setattr(pool_registry, "load", lambda: rows)
    seen = []

    def run(cmd):
        seen.append(cmd)
        if cmd[:2] == ["zpool", "get"]:
            return 1, "", "no such pool"
        if cmd == ["zpool", "import", "42"]:
            return 1, "", "cannot import 'tank': pool was previously in use from another system."
        return 0, "", ""

    assert "another system" in pool_registry.bring_back_all(run)["tank"]  # an ordinary start never forces
    assert ["zpool", "import", "-f", "42"] not in seen
    (tmp_path / pool_registry.ADOPT_FLAG).write_text(THEIRS)
    assert pool_registry.bring_back_all(run) == {"tank": ""}
    assert seen[-1] == ["zpool", "import", "-f", "42"]
    assert not os.path.exists(tmp_path / pool_registry.ADOPT_FLAG)  # once
    assert pool_registry.ADOPT_FLAG == pool_copy.ADOPT_FLAG


def test_a_pool_that_fails_for_another_reason_is_not_forced(tmp_path, monkeypatch):
    seen = []

    def run(cmd):
        seen.append(cmd)
        return (1, "", "no such pool") if cmd[:2] == ["zpool", "get"] else (1, "", "one or more devices is missing")

    row = {"name": "tank", "fs_type": "zfs", "uuid": "42", "mountpoint": "/mnt/storage/tank"}
    assert "devices is missing" in pool_registry.bring_back(row, run, force=True)
    assert ["zpool", "import", "-f", "42"] not in seen


# --- the routes -----------------------------------------------------------------------------------
def test_a_guest_has_nothing_to_look_for(client, auth_headers):
    assert client.get("/api/system/settings-copy/found", headers=auth_headers).json() == {"found": []}
    assert client.post("/api/system/settings-copy/look", headers=auth_headers).status_code == 404
    r = client.post(
        "/api/system/settings-copy/restore", headers=auth_headers, json={"key": "abc-def", "recovery_key": "x"}
    )
    assert r.status_code == 404


def test_look_then_restore_through_the_page(restorable, client, auth_headers, monkeypatch):
    recovery, calls, _data = restorable
    restarts = []
    monkeypatch.setattr(host_basics, "restart_kiboto", lambda: restarts.append(1) or True)
    monkeypatch.setattr(machine_key, "status", lambda do=None: {"managed": True, "locked": False})
    found = client.post("/api/system/settings-copy/look", headers=auth_headers).json()["found"]
    assert [c["key"] for c in found] == [f"{THEIRS}-media"]
    assert client.get("/api/system/settings-copy", headers=auth_headers).json()["found"] == found
    bad = client.post(
        "/api/system/settings-copy/restore", headers=auth_headers, json={"key": found[0]["key"], "recovery_key": "AAAA"}
    )
    assert bad.status_code == 400 and "recovery key" in bad.json()["detail"] and restarts == []
    ok = client.post(
        "/api/system/settings-copy/restore",
        headers=auth_headers,
        json={"key": found[0]["key"], "recovery_key": recovery},
    )
    assert ok.status_code == 200 and ok.json() == {"restored": 38, "name": "attic", "pool": "media", "restarting": True}
    assert restarts == [1] and "adopt" in calls
    client.cookies.clear()
    assert client.post("/api/system/settings-copy/look").status_code == 401


def test_the_copys_ai_databases_are_checked_with_its_own_key(restorable, monkeypatch):
    from backend import db_crypto

    recovery, calls, _data = restorable
    seen = []

    def restore_archive(f, passphrase="", snapshot=True, staged=False):
        seen.append((db_crypto._key_text(), db_crypto.enabled()))
        return {"restored": 1}

    monkeypatch.setattr(backup_engine, "restore_backup_archive", restore_archive)
    monkeypatch.delenv(db_crypto.KEY_ENV, raising=False)
    pool_copy.restore(f"{THEIRS}-media", recovery)
    assert seen == [(OLD_KEY, True)]  # opens_with_the_copys_own_key
    assert getattr(db_crypto._override, "text", "") == ""  # and only for that moment
