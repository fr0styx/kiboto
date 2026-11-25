"""A slowly read drive is checked for falling asleep or waking every minute (zero RPM waited up to
an hour for a drive that slept between two 30-minute reads)."""

import time

import pytest

from backend.hardware import disks, unraid
from backend.state import Z_STATE


@pytest.fixture
def rig(monkeypatch, tmp_path):
    now = time.time()
    polled = []
    monkeypatch.setattr(
        disks, "_discover_disks", lambda: [{"dev": "sda", "role": "data"}, {"dev": "sdb", "role": "parity"}]
    )
    monkeypatch.setattr(disks, "_hdd_interval", lambda dev, now: 1800.0)
    monkeypatch.setattr(
        disks, "_poll_one", lambda dev, is_nvme: polled.append(dev) or disks._SMART_IN_FLIGHT.discard(dev)
    )
    disks._SLEEP_CHECKED.clear()
    saved = dict(Z_STATE.cached_smart_data), dict(Z_STATE.last_smart_scan)
    for dev in ("sda", "sdb"):
        Z_STATE.cached_smart_data[dev] = (36, "ok")
        Z_STATE.last_smart_scan[dev] = now - 60  # read a minute ago: no full read is due
    yield polled
    Z_STATE.cached_smart_data.clear()
    Z_STATE.cached_smart_data.update(saved[0])
    Z_STATE.last_smart_scan.clear()
    Z_STATE.last_smart_scan.update(saved[1])


def test_unraid_spin_down_marks_the_drive_asleep_at_once(rig, monkeypatch):
    monkeypatch.setattr(unraid, "read_spin_states", lambda: {"sda": True, "sdb": False})
    disks.poll_all_disks_smart()
    assert Z_STATE.cached_smart_data["sda"] == (36, "standby")
    assert Z_STATE.cached_smart_data["sdb"] == (36, "ok")
    assert rig == []  # no drive was asked


def test_unraid_spin_up_reads_the_drive_that_slept(rig, monkeypatch):
    Z_STATE.cached_smart_data["sda"] = (36, "standby")
    monkeypatch.setattr(unraid, "read_spin_states", lambda: {"sda": False, "sdb": False})
    disks.poll_all_disks_smart()
    assert rig == ["sda"]


def test_once_a_minute(rig, monkeypatch):
    calls = []
    monkeypatch.setattr(unraid, "read_spin_states", lambda: calls.append(1) or {"sda": False, "sdb": False})
    disks.poll_all_disks_smart()
    disks.poll_all_disks_smart()
    assert len(calls) == 1


def test_elsewhere_only_a_sleeping_drive_is_asked(rig, monkeypatch):
    monkeypatch.setattr(unraid, "read_spin_states", lambda: None)
    Z_STATE.cached_smart_data["sdb"] = (35, "standby")
    disks.poll_all_disks_smart()
    assert rig == ["sdb"]  # sda is awake: its own sleep timer is left alone


def test_a_busy_drive_is_not_checked(rig, monkeypatch):
    monkeypatch.setattr(disks, "_hdd_interval", lambda dev, now: 45.0)
    for dev in ("sda", "sdb"):
        Z_STATE.last_smart_scan[dev] = time.time() - 10  # read ten seconds ago: not due
    monkeypatch.setattr(unraid, "read_spin_states", lambda: pytest.fail("asked for a busy drive"))
    disks.poll_all_disks_smart()
    assert rig == []


def test_read_spin_states_from_disks_ini(tmp_path, monkeypatch):
    (tmp_path / "var.ini").write_text("")
    (tmp_path / "disks.ini").write_text(
        '["parity"]\nname="parity"\ndevice="sdb"\nspundown="1"\n["disk1"]\ndevice="sda"\nspundown="0"\n["disk2"]\ndevice=""\n'
    )
    monkeypatch.setattr(unraid, "_find_emhttp_dir", lambda: str(tmp_path))
    assert unraid.read_spin_states() == {"sdb": True, "sda": False}
    monkeypatch.setattr(unraid, "_find_emhttp_dir", lambda: None)
    assert unraid.read_spin_states() is None
