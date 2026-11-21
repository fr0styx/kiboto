"""The data key of a machine set up for Kiboto: sealed to the machine, with a recovery key."""

import json
import os
import stat

import pytest

from backend import db_crypto, machine_key, runtime
from backend.services import host_basics


class Machine:
    """systemd-creds and systemd-analyze: seals to this machine's "chip" and opens only its own seals."""

    def __init__(self, chip=True):
        self.chip, self.board, self.seen, self.refuse = chip, "board-1", [], ()

    def __call__(self, cmd, feed=None, timeout=60):
        self.seen.append(cmd)
        if cmd[0] in self.refuse:
            return 1, "", "refused"
        if cmd[:2] == ["systemd-analyze", "has-tpm2"]:
            return (0 if self.chip else 1), "", ""
        if cmd[:2] == ["systemd-creds", "encrypt"]:
            with open(cmd[-1], "w", encoding="utf-8") as f:
                json.dump({"board": self.board, "how": cmd[3:-2], "key": feed}, f)
            return 0, "", ""
        if cmd[:2] == ["systemd-creds", "decrypt"]:
            with open(cmd[-2], encoding="utf-8") as f:
                sealed = json.load(f)
            if sealed["board"] != self.board:
                return 1, "", "WARNING:esys: Received TPM Error\nFailed to unseal"
            return 0, sealed["key"], ""
        return 0, "", ""

    def asked(self, *start):
        return [c for c in self.seen if c[: len(start)] == list(start)]


@pytest.fixture
def box(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    monkeypatch.setattr(machine_key, "DIR", str(tmp_path / "keys"))
    monkeypatch.setattr(machine_key, "_cache", {})
    monkeypatch.setattr(machine_key, "_refused_until", [0.0])
    monkeypatch.setattr(
        machine_key, "_stretched", lambda key, salt: (key.encode() + salt + b"0" * 32)[:32]
    )  # no slow KDF
    made = Machine()
    monkeypatch.setattr(machine_key, "run", made)
    return made


def keys(tmp_path):
    return sorted(os.listdir(tmp_path / "keys"))


def test_a_guest_has_no_key_of_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(machine_key, "DIR", str(tmp_path / "keys"))
    assert machine_key.ensure(do=Machine()) == "off"
    assert machine_key.status() == {"managed": False}
    assert machine_key.wanted() is False and not os.path.exists(tmp_path / "keys")


def test_a_recovery_key_is_easy_to_copy_and_forgiving_to_type():
    key = machine_key.new_recovery_key()
    groups = key.split("-")
    assert len(groups) == 6 and all(len(g) == 4 for g in groups)
    assert not set(key) & set("IO01") and key != machine_key.new_recovery_key()
    assert machine_key.tidy(key.lower().replace("-", " ")) == key
    assert machine_key.tidy(f"  {key}\n") == key
    for wrong in ("", "ABCD", key + "A", key.replace(key[0], "0", 1), "é" * 24):
        assert machine_key.tidy(wrong) == ""


def test_the_wrapped_copy_opens_only_with_its_recovery_key():
    key = machine_key.new_recovery_key()
    box = machine_key.wrap("a" * 64, key)
    assert machine_key.unwrap(box, key) == "a" * 64
    assert "a" * 16 not in json.dumps(box)
    other = machine_key.new_recovery_key()
    for bad_box, bad_key in ((box, other), ({**box, "key": box["salt"]}, key), ({}, key), ({**box, "salt": 5}, key)):
        with pytest.raises(machine_key.MachineKeyError, match="not this machine's recovery key"):
            machine_key.unwrap(bad_box, bad_key)


def test_the_first_start_makes_the_key_seals_it_to_the_chip_and_keeps_the_way_back(box, tmp_path):
    assert machine_key.ensure() == "made"
    assert keys(tmp_path) == ["data-key.cred", "data-key.recovery", "recovery-key", "state.json"]
    for name in keys(tmp_path)[:3]:
        assert stat.S_IMODE(os.stat(tmp_path / "keys" / name).st_mode) == 0o600, name
    assert stat.S_IMODE(os.stat(tmp_path / "keys").st_mode) == 0o700
    sealed = box.asked("systemd-creds", "encrypt")[0]
    assert sealed[2:5] == ["--name=kiboto-data-key", "--with-key=host+tpm2", "--tpm2-pcrs="]  # not bound to firmware
    key = machine_key.key_text()
    assert len(key) == 64 and key not in " ".join(sealed)  # the key goes in by a pipe, not on the command line
    recovery = machine_key.recovery_key_to_write_down()
    with open(tmp_path / "keys" / "data-key.recovery", encoding="utf-8") as f:
        assert machine_key.unwrap(json.load(f), recovery) == key
    assert machine_key.status() == {
        "managed": True,
        "on": True,
        "locked": False,
        "sealed_to": "chip",
        "to_write_down": True,
        "written_down_at": None,
    }
    assert machine_key.ensure() == "sealed" and len(box.asked("systemd-creds", "encrypt")) == 1


def test_a_machine_without_a_chip_seals_to_its_disk_and_says_so(box):
    box.chip = False
    machine_key.ensure()
    assert box.asked("systemd-creds", "encrypt")[0][3] == "--with-key=host"
    assert "--tpm2-pcrs=" not in box.asked("systemd-creds", "encrypt")[0]
    assert machine_key.status()["sealed_to"] == "disk"


def test_a_key_that_cannot_be_sealed_leaves_the_way_back_and_is_finished_next_time(box, tmp_path):
    box.refuse = ("systemd-creds",)
    with pytest.raises(machine_key.MachineKeyError, match="could not be sealed"):
        machine_key.ensure()
    assert "data-key.cred" not in keys(tmp_path) and "recovery-key" in keys(tmp_path)
    box.refuse = ()
    assert machine_key.ensure() == "sealed"  # the same key, sealed now
    with open(tmp_path / "keys" / "data-key.recovery", encoding="utf-8") as f:
        assert machine_key.unwrap(json.load(f), machine_key.recovery_key_to_write_down()) == machine_key.key_text()


def test_kiboto_forgets_the_recovery_key_once_it_is_written_down(box, tmp_path):
    machine_key.ensure()
    assert machine_key.written_down() is True
    assert "recovery-key" not in keys(tmp_path) and machine_key.recovery_key_to_write_down() == ""
    st = machine_key.status()
    assert st["to_write_down"] is False and st["written_down_at"] > 0
    assert machine_key.written_down() is False


def test_a_new_board_locks_the_key_and_the_recovery_key_opens_it(box):
    machine_key.ensure()
    key, recovery = machine_key.key_text(), machine_key.recovery_key_to_write_down()
    machine_key.written_down()
    machine_key._cache.clear()
    box.board = "board-2"  # the chip is another one
    with pytest.raises(machine_key.MachineKeyError, match="could not open its data key"):
        machine_key.key_text()
    asked = len(box.asked("systemd-creds", "decrypt"))
    with pytest.raises(machine_key.MachineKeyError):
        machine_key.key_text()
    assert len(box.asked("systemd-creds", "decrypt")) == asked  # the chip is not asked again at once
    assert machine_key.status()["locked"] is True and machine_key.ensure() == "sealed"  # nothing is made anew
    for wrong in ("", "nonsense", machine_key.new_recovery_key()):
        with pytest.raises(machine_key.MachineKeyError, match="not this machine's recovery key"):
            machine_key.unlock(wrong)
    assert machine_key.unlock(recovery.lower()) == "chip"
    assert machine_key.key_text() == key and machine_key.status()["locked"] is False


def test_only_the_wrapped_copy_as_after_setting_the_machine_up_again_waits_for_the_recovery_key(box, tmp_path):
    machine_key.ensure()
    key, recovery = machine_key.key_text(), machine_key.recovery_key_to_write_down()
    machine_key.written_down()
    os.remove(tmp_path / "keys" / "data-key.cred")
    machine_key._cache.clear()
    assert machine_key.wanted() is True and machine_key.ensure() == "locked"
    assert machine_key.status()["locked"] is True
    machine_key.unlock(recovery)
    assert machine_key.key_text() == key


def test_a_new_recovery_key_replaces_the_one_before(box, tmp_path):
    machine_key.ensure()
    old = machine_key.recovery_key_to_write_down()
    machine_key.written_down()
    assert machine_key.renew_recovery_key() is True
    new = machine_key.recovery_key_to_write_down()
    assert new and new != old and machine_key.status()["to_write_down"] is True
    with open(tmp_path / "keys" / "data-key.recovery", encoding="utf-8") as f:
        wrapped = json.load(f)
    assert machine_key.unwrap(wrapped, new) == machine_key.key_text()
    with pytest.raises(machine_key.MachineKeyError):
        machine_key.unwrap(wrapped, old)


def test_the_ai_databases_take_the_machines_key(box, monkeypatch):
    monkeypatch.setattr(db_crypto, "HAVE_SQLCIPHER", True)
    for name in (db_crypto.KEY_ENV, db_crypto.KEY_FILE_ENV, "CREDENTIALS_DIRECTORY"):
        monkeypatch.delenv(name, raising=False)
    assert db_crypto.enabled() is False and db_crypto._key_text() == ""  # before the first start
    machine_key.ensure()
    assert db_crypto.enabled() is True and db_crypto._key_text() == machine_key.key_text()
    monkeypatch.setenv(db_crypto.KEY_ENV, "a-key-from-the-settings")
    assert db_crypto._key_text() == "a-key-from-the-settings"  # a key someone set still wins
    monkeypatch.delenv(db_crypto.KEY_ENV)
    machine_key._cache.clear()
    box.board = "board-2"
    with pytest.raises(db_crypto.DataKeyError, match="Type the recovery key"):
        db_crypto._key_text()
    monkeypatch.setattr(db_crypto, "HAVE_SQLCIPHER", False)
    assert db_crypto.enabled() is False and db_crypto._key_text() == ""  # a build that cannot encrypt


def test_the_machine_restarts_kiboto_only_where_it_runs_it(box, monkeypatch):
    seen = []
    monkeypatch.setattr(host_basics, "run", lambda cmd, timeout=20: (seen.append(cmd), (0, ""))[1])
    assert host_basics.restart_kiboto() is True
    assert seen == [["systemd-run", "--quiet", "--collect", "--on-active=2", "systemctl", "restart", "kiboto.service"]]
    monkeypatch.setattr(host_basics, "run", lambda cmd, timeout=20: (1, "no"))
    assert host_basics.restart_kiboto() is False
    monkeypatch.setattr(runtime, "MANAGED_MARK", "/nonexistent/managed")
    assert host_basics.restart_kiboto() is False


# --- the routes -----------------------------------------------------------------------------------
KEY = "/api/system/machine/key"


def test_a_guest_answers_that_it_has_none(client, auth_headers):
    assert client.get(KEY, headers=auth_headers).json() == {"managed": False}
    for path in ("recovery-key", "written-down", "new-recovery-key"):
        assert client.post(f"{KEY}/{path}", headers=auth_headers).status_code == 404
    assert client.post(f"{KEY}/unlock", headers=auth_headers, json={"recovery_key": "x"}).status_code == 404


def test_the_recovery_key_is_shown_until_it_is_written_down(box, client, auth_headers):
    machine_key.ensure()
    client.cookies.clear()  # nobody is signed in
    assert client.get(KEY).status_code == 401
    assert client.post(f"{KEY}/recovery-key").status_code == 401
    st = client.get(KEY, headers=auth_headers).json()
    assert st["to_write_down"] is True and "recovery" not in json.dumps(st)
    shown = client.post(f"{KEY}/recovery-key", headers=auth_headers).json()["recovery_key"]
    assert shown == machine_key.recovery_key_to_write_down()
    after = client.post(f"{KEY}/written-down", headers=auth_headers).json()
    assert after["to_write_down"] is False and after["written_down_at"]
    assert client.post(f"{KEY}/recovery-key", headers=auth_headers).status_code == 409


def test_unlocking_seals_again_and_restarts_kiboto(box, client, auth_headers, monkeypatch):
    machine_key.ensure()
    recovery = machine_key.recovery_key_to_write_down()
    machine_key._cache.clear()
    box.board = "board-2"
    restarts = []
    monkeypatch.setattr(host_basics, "restart_kiboto", lambda: restarts.append(1) or True)
    assert client.get(KEY, headers=auth_headers).json()["locked"] is True
    r = client.post(f"{KEY}/unlock", headers=auth_headers, json={"recovery_key": "AAAA-AAAA-AAAA-AAAA-AAAA-AAAA"})
    assert r.status_code == 400 and "not this machine's recovery key" in r.json()["detail"] and restarts == []
    r = client.post(f"{KEY}/unlock", headers=auth_headers, json={"recovery_key": recovery})
    assert r.status_code == 200 and r.json()["locked"] is False and r.json()["restarting"] is True
    assert restarts == [1]


@pytest.mark.real_confirmations
def test_a_new_recovery_key_is_asked_first(box, client, auth_headers, monkeypatch):
    machine_key.ensure()
    old = machine_key.recovery_key_to_write_down()
    machine_key.written_down()
    monkeypatch.setattr(host_basics, "host_name", lambda: "attic")
    r = client.post(f"{KEY}/new-recovery-key", headers=auth_headers)
    assert r.status_code == 428 and r.json()["action"] == "system.new_recovery_key"
    token = client.post(
        "/api/confirmations", headers=auth_headers, json={"action": "system.new_recovery_key", "target": "attic"}
    ).json()["token"]
    r = client.post(f"{KEY}/new-recovery-key", headers={**auth_headers, "X-Confirm-Token": token})
    assert r.status_code == 200 and r.json()["to_write_down"] is True
    assert machine_key.recovery_key_to_write_down() not in ("", old)
