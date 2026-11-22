"""iSCSI on a machine set up for Kiboto: tgtd as a service of the machine, not a container."""

import pytest

from backend import runtime
from backend.services import host_basics, iscsi_target

DISK = {
    "id": "d1",
    "name": "games",
    "folder": "/mnt/storage/tank/disks",
    "file": "games.img",
    "size_gb": 10,
    "user": "pc",
    "secret": "x",
}


@pytest.fixture
def machine(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    monkeypatch.setattr(iscsi_target, "CONF_DIR", str(tmp_path / "iscsi"))
    monkeypatch.setattr(iscsi_target, "conf_text", lambda disks: f"tgtadm # {len(disks)} disks\n")
    monkeypatch.setattr(iscsi_target, "_docker", lambda *a, **k: pytest.fail("no container on a machine of its own"))
    state = {"enabled": True, "disks": [DISK]}
    monkeypatch.setattr(iscsi_target, "_read", lambda: state)
    monkeypatch.setattr(iscsi_target, "disks", lambda: state["disks"])
    seen, unit = [], {"on": False, "described": ""}

    def run(cmd, timeout=20):
        seen.append(cmd)
        if cmd[:2] == ["systemctl", "is-active"]:
            return (0, "active") if unit["on"] else (3, "inactive")
        if cmd[:2] == ["systemctl", "show"]:
            return 0, unit["described"]
        if cmd[0] == "systemd-run":
            unit["on"], unit["described"] = True, cmd[cmd.index("--description") + 1]
        if cmd[:2] == ["systemctl", "stop"]:
            unit["on"] = False
        return 0, ""

    monkeypatch.setattr(host_basics, "run", run)
    return state, seen, unit


def test_tgtd_runs_as_a_service_reading_kibotos_own_file(machine, tmp_path):
    state, seen, unit = machine
    st = iscsi_target.ensure()
    assert st["running"] is True and st["error"] == ""
    started = next(c for c in seen if c[0] == "systemd-run")
    assert started[started.index("--unit") + 1] == "kiboto-iscsi"
    assert (
        started[-3:-1] == ["sh", "-c"] and f"sh {tmp_path}/iscsi/setup.sh" in started[-1] and "tgtd -f" in started[-1]
    )
    assert (tmp_path / "iscsi" / "setup.sh").read_text() == "tgtadm # 1 disks\n"


def test_an_unchanged_service_is_left_running_and_a_change_starts_it_anew(machine):
    state, seen, unit = machine
    iscsi_target.ensure()
    seen.clear()
    assert iscsi_target.ensure()["running"] is True
    assert not [c for c in seen if c[0] == "systemd-run"]
    state["disks"] = [DISK, {**DISK, "id": "d2", "name": "vms"}]
    iscsi_target.ensure()
    assert ["systemctl", "stop", "kiboto-iscsi"] in seen and [c for c in seen if c[0] == "systemd-run"]


def test_turned_off_or_without_disks_it_stops(machine):
    state, seen, unit = machine
    iscsi_target.ensure()
    state["enabled"] = False
    assert iscsi_target.ensure()["running"] is False and unit["on"] is False
    state["enabled"], state["disks"] = True, []
    assert iscsi_target.ensure()["running"] is False


def test_a_service_that_does_not_run_says_why(machine, monkeypatch):
    state, seen, unit = machine
    assert iscsi_target.status()["why"] == "down"
    monkeypatch.setattr(
        host_basics, "run", lambda cmd, timeout=20: (1, "failed") if cmd[0] == "systemd-run" else (3, "inactive")
    )
    st = iscsi_target.ensure()
    assert st["running"] is False and st["why"] == "start"
