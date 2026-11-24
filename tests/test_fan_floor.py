"""The fan safety floor (45 -> 52 °C under every mode while a drive spins), Zero RPM still winning
while every drive sleeps, a spinning drive without a reading counting as hot after 3 minutes, and
readings of idle disks kept as long as their read interval."""

import types

import pytest

from backend.hardware import disks as disks_mod
from backend.hardware import pal_storage
from backend.hardware.fans import FAN_MAX_PWM, FAN_MIN_PWM, floor_pwm
from backend.services import fan_control
from backend.state import Z_STATE


def test_floor_curve():
    assert floor_pwm(None) == FAN_MIN_PWM
    assert floor_pwm(40) == FAN_MIN_PWM
    assert floor_pwm(45) == FAN_MIN_PWM
    assert floor_pwm(48.5) == int(FAN_MIN_PWM + 0.5 * (FAN_MAX_PWM - FAN_MIN_PWM))
    assert floor_pwm(52) == FAN_MAX_PWM
    assert floor_pwm(60) == FAN_MAX_PWM


class Rig:
    def __init__(self, monkeypatch):
        self.now = 1_790_000_000.0
        self.zones = {}
        self.events = []
        clock = types.SimpleNamespace(time=lambda: self.now, monotonic=lambda: 50_000.0, sleep=lambda s: None)
        monkeypatch.setattr(fan_control, "apply_zone_pwm", self._zone)
        monkeypatch.setattr(fan_control, "set_fan_pwm", lambda *a, **k: True)
        monkeypatch.setattr(fan_control, "read_unraid_status", lambda *a, **k: {})
        monkeypatch.setattr(fan_control, "add_event", lambda *a, **k: self.events.append(a))
        monkeypatch.setattr(fan_control, "time", clock)
        monkeypatch.setattr(
            pal_storage, "get_storage_platform", lambda *a, **k: types.SimpleNamespace(is_storage_busy=lambda: False)
        )
        Z_STATE.fan_state_tracker.clear()
        Z_STATE.critical_temp_active = False
        Z_STATE.critical_alert_at = 0.0
        Z_STATE.thermal_watchdog_engaged = False
        Z_STATE.drive_unread_since.clear()
        Z_STATE.drive_unread_alerted.clear()

    def _zone(self, zone, target, *a, **k):
        self.zones[zone] = target
        return target

    def run(self, disks, profile="balanced", fan_cfg=None, zero_rpm=False):
        fan_control.run_fan_control(
            cpu_hold_secs=30,
            cpu_temp=45,
            ctrl_cpu_fan=False,
            disk_hold_secs=0,
            disks=disks,
            fan_cfg=fan_cfg or {},
            profile=profile,
            temp_max=50,
            temp_min=37,
            zero_rpm_enabled=zero_rpm,
            zero_rpm_nvme_ceiling=50,
            zero_rpm_stop_delay=0,
            zero_rpm_stop_temp=35,
        )
        return self.zones[1], self.zones[2]


@pytest.fixture
def rig(monkeypatch):
    return Rig(monkeypatch)


def test_floor_lifts_a_flat_own_curve(rig):
    own = {"curve_points": [[30, 0], [60, 32]]}
    assert rig.run([{"dev": "sda", "role": "data", "temp": 50}], profile="auto", fan_cfg=own) == (
        floor_pwm(50),
        floor_pwm(50),
    )


def test_floor_lifts_a_fixed_speed(rig):
    got = rig.run([{"dev": "sda", "role": "data", "temp": 51}], profile="manual", fan_cfg={"manual_pct": 40})
    assert got == (floor_pwm(51), floor_pwm(51))


def test_a_cool_drive_leaves_the_mode_alone(rig):
    got = rig.run([{"dev": "sda", "role": "data", "temp": 40}], profile="manual", fan_cfg={"manual_pct": 40})
    assert got == (int(0.4 * FAN_MAX_PWM), int(0.4 * FAN_MAX_PWM))


def test_zero_rpm_still_stops_the_fans_while_every_drive_sleeps(rig):
    asleep = [{"dev": "sda", "role": "data", "temp": 53, "standby": True}]  # last reading before it slept
    assert rig.run(asleep, zero_rpm=True) == (0, 0)


def test_spinning_drive_without_a_reading_counts_as_hot_after_3_minutes(rig):
    unread = [{"dev": "sda", "role": "data", "temp": None}, {"dev": "sdb", "role": "data", "temp": 38}]
    first = rig.run([dict(d) for d in unread])
    assert first[0] < FAN_MAX_PWM and not rig.events
    rig.now += 179
    assert rig.run([dict(d) for d in unread])[0] < FAN_MAX_PWM
    rig.now += 2
    assert rig.run([dict(d) for d in unread]) == (FAN_MAX_PWM, FAN_MAX_PWM)
    assert len(rig.events) == 1 and "sda" in rig.events[0][2]
    rig.now += 30
    assert rig.run([dict(d) for d in unread]) == (FAN_MAX_PWM, FAN_MAX_PWM)
    assert len(rig.events) == 1  # notified once
    back = [{"dev": "sda", "role": "data", "temp": 39}, {"dev": "sdb", "role": "data", "temp": 38}]
    assert rig.run(back)[0] < FAN_MAX_PWM
    assert not Z_STATE.drive_unread_since and not Z_STATE.drive_unread_alerted


def test_sleeping_drive_without_a_reading_is_not_hot(rig):
    asleep = [{"dev": "sda", "role": "data", "temp": None, "standby": True}, {"dev": "sdb", "role": "data", "temp": 38}]
    rig.run([dict(d) for d in asleep])
    rig.now += 600
    assert rig.run([dict(d) for d in asleep])[0] < FAN_MAX_PWM
    assert not rig.events


@pytest.fixture
def one_disk(monkeypatch):
    monkeypatch.setattr(disks_mod, "_discover_disks", lambda: [{"dev": "sda", "role": "data"}])
    saved = (dict(Z_STATE.cached_smart_data), dict(Z_STATE.cached_smart_time))
    yield
    Z_STATE.cached_smart_data.clear()
    Z_STATE.cached_smart_data.update(saved[0])
    Z_STATE.cached_smart_time.clear()
    Z_STATE.cached_smart_time.update(saved[1])


def _reading_age(seconds):
    import time

    Z_STATE.cached_smart_data["sda"] = (41, "ok")
    Z_STATE.cached_smart_time["sda"] = time.time() - seconds


def test_idle_disk_keeps_its_reading_between_slow_reads(monkeypatch, one_disk):
    monkeypatch.setattr(disks_mod, "_hdd_interval", lambda dev, now: 1800.0)
    _reading_age(1200)
    assert disks_mod.read_disk_temps_and_io()[0]["temp"] == 41


def test_busy_disk_reading_goes_stale_when_reads_stop(monkeypatch, one_disk):
    monkeypatch.setattr(disks_mod, "_hdd_interval", lambda dev, now: 45.0)
    _reading_age(300)
    d = disks_mod.read_disk_temps_and_io()[0]
    assert d["temp"] is None and d["health"] == "unknown"
