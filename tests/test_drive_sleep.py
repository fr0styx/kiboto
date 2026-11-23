"""Let hard drives sleep: off by default, only on a managed host, and a sleeping drive is never woken."""

import json

import pytest

from backend.hardware import drive_sleep as hw
from backend.services import drive_sleep as svc

TREE = {
    "blockdevices": [
        {
            "name": "sda",
            "type": "disk",
            "rota": True,
            "tran": "sata",
            "children": [{"name": "sda1", "mountpoints": ["/"]}],
        },
        {"name": "sdb", "type": "disk", "rota": True, "tran": "sata", "mountpoints": [None]},
        {"name": "sdc", "type": "disk", "rota": "1", "tran": "sas", "children": [{"name": "sdc1", "mountpoints": []}]},
        {"name": "sdd", "type": "disk", "rota": False, "tran": "sata"},
        {"name": "sde", "type": "disk", "rota": True, "tran": "usb"},
        {
            "name": "sdf",
            "type": "disk",
            "rota": True,
            "tran": "sata",
            "children": [{"name": "sdf1", "mountpoints": ["[SWAP]"]}],
        },
        {"name": "vda", "type": "disk", "rota": True, "tran": None},
        {"name": "sr0", "type": "rom", "rota": True, "tran": "sata"},
        {"name": "nvme0n1", "type": "disk", "rota": False, "tran": "nvme"},
    ]
}


class Host:
    def __init__(self, tree=TREE, refuse=()):
        self.tree, self.refuse, self.calls = tree, refuse, []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[0] == "lsblk":
            return (0, json.dumps(self.tree)) if self.tree is not None else (1, "no lsblk")
        return (5, "SG_IO: bad/missing sense data") if any(cmd[-1].endswith(r) for r in self.refuse) else (0, "")

    def hdparm(self):
        return [c for c in self.calls if c[0] == "hdparm"]


def test_timer_numbers_follow_hdparm():
    assert [hw.timer_code(m) for m in (0, 10, 15, 20, 30, 60, 120, 180)] == [0, 120, 180, 240, 241, 242, 244, 246]
    assert hw.timer_code(-5) == 0 and hw.timer_code(600) == 251


def test_only_spinning_data_drives_get_a_timer():
    assert hw.spinning_drives(Host()) == ["sdb", "sdc"]
    assert hw.spinning_drives(Host(tree=None)) == []
    assert hw.spinning_drives(lambda cmd: (0, "not json")) == []


def test_a_sleeping_drive_is_left_alone_and_a_refusal_is_said():
    host = Host(refuse=("sdc",))
    rows = hw.apply(20, host, probe=lambda name: "standby" if name == "sdb" else "active")
    assert rows == [
        {"drive": "sdb", "state": "asleep"},
        {"drive": "sdc", "state": "failed", "said": "SG_IO: bad/missing sense data"},
    ]
    assert [c[:3] for c in host.hdparm()] == [["hdparm", "-S", "240"]]
    host = Host()
    assert [r["state"] for r in hw.apply(0, host, probe=lambda name: "active")] == ["set", "set"]
    assert {c[2] for c in host.hdparm()} == {"0"}


VM_SAID = (
    "\n/dev/sda:\n setting standby to 120 (10 minutes)\n"
    "SG_IO: bad/missing sense data, sb[]:  70 00 05 00 00 00 00 0a 00 00 00 00 20 00 00 00 00 00"
)


def test_a_drive_that_answers_illegal_request_did_not_take_the_timer():
    assert hw.refused(VM_SAID)
    assert hw.refused("sb[]:  72 05 20 00")
    assert not hw.refused("sb[]:  70 00 06 00") and not hw.refused("sb[]:  72 06 00") and not hw.refused("")
    assert not hw.refused("sb[]:  00 00 05")
    host = Host()

    def host_run(cmd):
        return (0, VM_SAID) if cmd[0] == "hdparm" else host(cmd)

    rows = hw.apply(10, host_run, probe=lambda name: "active")
    assert [r["state"] for r in rows] == ["failed", "failed"] and rows[0]["said"].endswith("00 00")


def test_run_says_what_happened(monkeypatch):
    assert hw.run(["true"])[0] == 0
    assert hw.run(["/nonexistent/hdparm"])[0] == 127


@pytest.fixture
def setting(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "STATE_FILE", str(tmp_path / "drive_sleep.json"))
    monkeypatch.setattr(svc.runtime, "managed_host", lambda: True)
    applied = []
    monkeypatch.setattr(svc.drive_sleep, "apply", lambda m: applied.append(m) or [{"drive": "sdb", "state": "set"}])
    return applied


def test_off_by_default_and_only_where_kiboto_is_the_system(setting, monkeypatch, tmp_path):
    assert svc.public_state() == {"minutes": 0, "last": [], "choices": list(hw.CHOICES), "applies": True}
    assert svc.at_start() == [] and setting == []
    with pytest.raises(ValueError, match="one of the times"):
        svc.save(7)
    st = svc.save(30)
    assert st["minutes"] == 30 and st["last"] == [{"drive": "sdb", "state": "set"}] and setting == [30]
    assert svc.at_start() == [{"drive": "sdb", "state": "set"}] and setting == [30, 30]
    (tmp_path / "drive_sleep.json").write_text('{"minutes": 7}')
    assert svc.state()["minutes"] == 0
    monkeypatch.setattr(svc.runtime, "managed_host", lambda: False)
    assert svc.public_state()["applies"] is False and svc.at_start() == []
    with pytest.raises(ValueError, match="its own system decides"):
        svc.save(10)


def test_routes(client, auth_headers, setting, monkeypatch):
    assert client.get("/api/system/drive-sleep", headers=auth_headers).json()["minutes"] == 0
    ok = client.put("/api/system/drive-sleep", headers=auth_headers, json={"minutes": 60})
    assert ok.status_code == 200 and ok.json()["minutes"] == 60
    bad = client.put("/api/system/drive-sleep", headers=auth_headers, json={"minutes": 7})
    assert bad.status_code == 400 and "srv.drive_sleep_choice" in bad.text
    monkeypatch.setattr(svc.runtime, "managed_host", lambda: False)
    bad = client.put("/api/system/drive-sleep", headers=auth_headers, json={"minutes": 10})
    assert bad.status_code == 400 and "srv.drive_sleep_not_here" in bad.text


def test_only_a_listed_time_reaches_hdparm():
    with pytest.raises(ValueError):
        hw.apply(7, Host(), probe=lambda name: "active")
    assert hw.CODES[180] == 246
