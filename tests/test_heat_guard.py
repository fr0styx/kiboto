"""Switch off when too hot (hardware report extra, off by default): warns at once, acts after three
minutes, never counts a sleeping drive, re-arms once cool, and asks for a hand switch-off where it can't."""

import pytest

from backend.services import heat_guard


@pytest.fixture
def guard(monkeypatch, tmp_path):
    monkeypatch.setattr(heat_guard, "SETTINGS_FILE", str(tmp_path / "heat.json"))
    monkeypatch.setattr(heat_guard, "_state", {"since": {}, "warned": False, "engaged": False})
    sent = []
    monkeypatch.setattr(heat_guard, "_notify", lambda title, message, level, alert, **p: sent.append((alert, p)))
    monkeypatch.setattr(heat_guard, "can_power_off", lambda: True)
    started = []
    return {"sent": sent, "start": started.append, "started": started}


HOT = [{"name": "sdb", "temp": 61}, {"name": "sdc", "temp": 40}]


def test_off_by_default_does_nothing(guard):
    assert heat_guard.enabled() is False
    assert heat_guard.check(HOT, now=0, start=guard["start"]) is None
    assert heat_guard.check(HOT, now=999, start=guard["start"]) is None
    assert guard["sent"] == [] and guard["started"] == []


def test_warns_at_once_then_acts_after_three_minutes(guard):
    heat_guard.set_enabled(True)
    assert heat_guard.check(HOT, now=0, start=guard["start"]) == "warned"
    assert guard["sent"] == [("heat_warn", {"drives": "sdb 61 °C", "minutes": 3})]
    assert heat_guard.check(HOT, now=100, start=guard["start"]) is None
    assert heat_guard.check(HOT, now=180, start=guard["start"]) == "engaged"
    assert guard["started"] == [[("sdb", 61, 60)]]
    # once engaged it does not start again until cool
    assert heat_guard.check(HOT, now=500, start=guard["start"]) is None
    assert heat_guard.check([{"name": "sdb", "temp": 56}], now=600, start=guard["start"]) is None
    assert heat_guard.public_state()["engaged"] is True
    assert heat_guard.check([{"name": "sdb", "temp": 54}], now=700, start=guard["start"]) is None
    assert heat_guard.public_state()["engaged"] is False


def test_cooling_down_in_time_starts_over(guard):
    heat_guard.set_enabled(True)
    heat_guard.check(HOT, now=0, start=guard["start"])
    heat_guard.check([{"name": "sdb", "temp": 58}], now=100, start=guard["start"])
    assert heat_guard.check(HOT, now=150, start=guard["start"]) == "warned"
    assert heat_guard.check(HOT, now=300, start=guard["start"]) is None
    assert heat_guard.check(HOT, now=330, start=guard["start"]) == "engaged"


def test_sleeping_and_unread_drives_and_nvme_limits(guard):
    heat_guard.set_enabled(True)
    calm = [{"name": "sdb", "temp": 70, "standby": True}, {"name": "sdd", "temp": None}, {"dev": "nvme0n1", "temp": 79}]
    assert heat_guard.check(calm, now=0, start=guard["start"]) is None
    assert heat_guard.check([{"dev": "nvme0n1", "temp": 80}], now=0, start=guard["start"]) == "warned"
    assert guard["sent"][-1][1]["drives"] == "nvme0n1 80 °C"


def test_where_it_cannot_switch_off_it_warns_about_the_apps(guard, monkeypatch):
    monkeypatch.setattr(heat_guard, "can_power_off", lambda: False)
    heat_guard.set_enabled(True)
    heat_guard.check(HOT, now=0, start=guard["start"])
    assert guard["sent"][0][0] == "heat_warn_apps"


def test_turning_it_off_forgets_the_count(guard):
    heat_guard.set_enabled(True)
    heat_guard.check(HOT, now=0, start=guard["start"])
    heat_guard.set_enabled(False)
    heat_guard.set_enabled(True)
    assert heat_guard.check(HOT, now=200, start=guard["start"]) == "warned"


@pytest.fixture
def quiet_steps(monkeypatch):
    from backend import state
    from backend.services import host_power

    done = []
    monkeypatch.setattr(heat_guard, "_machines", lambda: done.append("vms"))
    monkeypatch.setattr(heat_guard, "_apps", lambda: done.append("apps"))
    monkeypatch.setattr(heat_guard.os, "sync", lambda: done.append("sync"))
    monkeypatch.setattr(state, "add_event", lambda *a, **k: done.append("event"))
    monkeypatch.setattr(host_power, "run", lambda action, *a: done.append(action) or {"started": True})
    return done


def test_switch_off_stops_everything_then_the_nas(guard, quiet_steps):
    assert heat_guard.switch_off([("sdb", 61, 60)]) == "off"
    assert quiet_steps == ["event", "vms", "apps", "sync", "shutdown"]
    assert guard["sent"] == []
    last = heat_guard.public_state()["last"]
    assert last["outcome"] == "off" and last["drives"] == "sdb 61 °C"


def test_switch_off_by_hand_where_it_cannot(guard, quiet_steps, monkeypatch):
    monkeypatch.setattr(heat_guard, "can_power_off", lambda: False)
    assert heat_guard.switch_off([("sdb", 61, 60)]) == "by_hand"
    assert "shutdown" not in quiet_steps and "apps" in quiet_steps
    assert guard["sent"] == [("heat_manual", {"drives": "sdb 61 °C"})]


def test_a_failed_switch_off_asks_for_a_hand(guard, quiet_steps, monkeypatch):
    from backend.services import host_power

    monkeypatch.setattr(host_power, "run", lambda action, *a: {"started": False})
    assert heat_guard.switch_off([("sdb", 61, 60)]) == "failed"
    assert guard["sent"][0][0] == "heat_manual"


def test_a_failing_step_does_not_stop_the_rest(guard, quiet_steps, monkeypatch):
    def boom():
        raise RuntimeError("docker gone")

    monkeypatch.setattr(heat_guard, "_apps", boom)
    assert heat_guard.switch_off([("sdb", 61, 60)]) == "off"
    assert "sync" in quiet_steps


def test_the_routes(client, auth_headers, guard):
    r = client.get("/api/system/heat-shutdown", headers=auth_headers)
    assert r.status_code == 200 and r.json()["enabled"] is False and r.json()["hdd_c"] == 60
    r = client.put("/api/system/heat-shutdown", headers=auth_headers, json={"enabled": True})
    assert r.status_code == 200 and r.json()["enabled"] is True
