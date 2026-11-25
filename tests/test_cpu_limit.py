"""The processor counts as critical 15 °C under the limit it reports (owner, 25 Nov 2026), else 80 °C."""

import pytest

from backend.hardware import cpu
from backend.hardware.cpu import read_cpu_limit as real_read_cpu_limit  # before the test setup swaps it
from backend.services import fan_control
from backend.state import Z_STATE


@pytest.fixture
def chip(tmp_path, monkeypatch):
    """A coretemp chip in a stand-in /sys, read afresh."""
    hw = tmp_path / "class" / "hwmon" / "hwmon3"
    hw.mkdir(parents=True)
    (hw / "name").write_text("coretemp\n")
    (hw / "temp1_input").write_text("76000\n")
    monkeypatch.setattr(cpu, "HOST_SYS", str(tmp_path))
    monkeypatch.setattr(Z_STATE, "cached_cpu_temp_path", None)
    monkeypatch.setattr(cpu, "_limit", {"at": 0.0, "value": None})
    return hw


def test_the_limit_comes_from_the_sensor_chip(chip):
    (chip / "temp1_crit").write_text("110000\n")
    assert real_read_cpu_limit() == 110


def test_max_when_there_is_no_crit_and_nothing_implausible(chip, monkeypatch):
    (chip / "temp1_max").write_text("100000\n")
    assert real_read_cpu_limit() == 100
    monkeypatch.setattr(cpu, "_limit", {"at": 0.0, "value": None})
    (chip / "temp1_max").write_text("255000\n")  # a nonsense value counts as none
    assert real_read_cpu_limit() is None


def test_read_once_an_hour(chip, monkeypatch):
    (chip / "temp1_crit").write_text("110000\n")
    assert real_read_cpu_limit() == 110
    (chip / "temp1_crit").write_text("100000\n")
    assert real_read_cpu_limit() == 110


def test_critical_is_fifteen_under_the_limit_or_eighty(monkeypatch):
    monkeypatch.setattr(cpu, "read_cpu_limit", lambda: 110.0)
    assert fan_control.cpu_critical_c() == 95
    monkeypatch.setattr(cpu, "read_cpu_limit", lambda: None)
    assert fan_control.cpu_critical_c() == 80


def test_a_core_ultra_at_88_no_longer_forces_full_speed(monkeypatch):
    monkeypatch.setattr(cpu, "read_cpu_limit", lambda: 110.0)
    monkeypatch.setattr(fan_control, "add_event", lambda *a, **k: None)
    Z_STATE.critical_temp_active = False
    Z_STATE.cpu_hot_since = 0.0
    now = [1_000_000.0]
    monkeypatch.setattr(fan_control.time, "time", lambda: now[0])
    assert fan_control._cpu_critical(88, False) is False
    assert fan_control._cpu_critical(96, False) is False  # not yet held six seconds
    now[0] += fan_control.CPU_SUSTAIN_SECS
    assert fan_control._cpu_critical(96, False) is True
