"""From a D4 field report (#71): two pwm-fan devices, fans the host runs itself, a backlight Kiboto
cannot write, and a Mali GPU's clock."""

import os
from types import SimpleNamespace

import pytest

from backend.hardware import fans, host_telemetry, screen
from backend.state import Z_STATE


def _fan_device(root, n, rpm, name="pwmfan", pwm=True):
    d = root / f"hwmon{n}"
    d.mkdir(parents=True)
    (d / "name").write_text(name + "\n")
    if rpm is not None:
        (d / "fan1_input").write_text(f"{rpm}\n")
    if pwm:
        (d / "pwm1").write_text("150\n")
    return str(d)


@pytest.fixture(autouse=True)
def _mode():
    before = Z_STATE.fan_driver_mode
    yield
    Z_STATE.fan_driver_mode = before


def test_both_fans_of_two_pwm_fan_devices_are_read_in_order(tmp_path, monkeypatch):
    first = _fan_device(tmp_path, 0, 3010)
    _fan_device(tmp_path, 1, 2980)
    _fan_device(tmp_path, 2, 1200, name="nct6775")  # another driver: not one of these fans
    monkeypatch.setattr(fans, "_find_hwmon", lambda: first)
    monkeypatch.delenv(fans.FAN_HOST_ENV, raising=False)
    assert fans.read_fans() == [3010, 2980]
    assert Z_STATE.fan_driver_mode == "hwmon"
    (tmp_path / "hwmon1" / "fan1_input").write_text("x\n")  # an unreadable one keeps its place
    assert fans.read_fans() == [3010, 0]


def test_a_host_that_runs_its_fans_is_only_read(tmp_path, monkeypatch):
    first = _fan_device(tmp_path, 0, 3000)
    monkeypatch.setattr(fans, "_find_hwmon", lambda: first)
    written = []
    monkeypatch.setattr(fans, "_write_sysfs", lambda path, value: written.append(path) or True)
    monkeypatch.setenv(fans.FAN_HOST_ENV, "1")
    assert fans.host_runs_fans(first) is True
    assert fans.set_fan_pwm("auto", custom_pwms={"pwm1": 120}) is False
    assert fans.failsafe_release_fans("shutdown") is False
    assert written == [] and Z_STATE.fan_driver_mode == "host"
    assert fans.read_fans() == [3000] and Z_STATE.fan_driver_mode == "host"


def test_a_read_only_fan_device_is_taken_as_the_hosts(tmp_path, monkeypatch):
    first = _fan_device(tmp_path, 0, 3000)
    monkeypatch.delenv(fans.FAN_HOST_ENV, raising=False)
    monkeypatch.setattr(fans.os, "statvfs", lambda p: SimpleNamespace(f_flag=os.ST_RDONLY))
    assert fans.host_runs_fans(first) is True
    monkeypatch.setattr(fans.os, "statvfs", lambda p: SimpleNamespace(f_flag=0))
    assert fans.host_runs_fans(first) is False
    assert fans.host_runs_fans(None) is False

    def gone(p):
        raise OSError("gone")

    monkeypatch.setattr(fans.os, "statvfs", gone)
    assert fans.host_runs_fans(first) is False
    (tmp_path / "hwmon0" / "name").unlink()
    assert fans._same_kind(first) == []


def test_a_backlight_kiboto_cannot_write_is_said_once_and_left_alone(tmp_path, monkeypatch):
    bl = tmp_path / "backlight"
    bl.mkdir()
    (bl / "brightness").write_text("100\n")
    (bl / "max_brightness").write_text("255\n")
    monkeypatch.setattr(screen, "discover_backlight_dir", lambda: str(bl))
    monkeypatch.setattr(screen, "set_fb_blank", lambda on: None)
    monkeypatch.setattr(screen, "_BACKLIGHT_SAID", {"read_only": False})
    monkeypatch.setattr(screen.os, "access", lambda p, mode: False)
    assert screen.backlight_writable() is False
    assert screen.set_screen_brightness(40) is False and screen.set_screen_brightness(41) is False
    assert (bl / "brightness").read_text() == "100\n" and screen._BACKLIGHT_SAID["read_only"] is True
    monkeypatch.setattr(screen.os, "access", lambda p, mode: True)
    assert screen.backlight_writable() is True
    monkeypatch.setattr(screen, "discover_backlight_dir", lambda: None)
    assert screen.backlight_writable() is False


def test_the_page_is_told_whether_brightness_can_be_set(client, auth_headers, monkeypatch):
    from backend.api import stats

    monkeypatch.setattr(stats, "backlight_writable", lambda: False)
    assert client.get("/api/lcd_status", headers=auth_headers).json()["brightness_possible"] is False


def test_a_mali_gpu_tells_its_clock_through_devfreq(tmp_path, monkeypatch):
    gpu = tmp_path / "class" / "devfreq" / "fb000000.gpu"
    gpu.mkdir(parents=True)
    (gpu / "cur_freq").write_text("300000000\n")
    (gpu / "max_freq").write_text("1000000000\n")
    monkeypatch.setattr(host_telemetry, "HOST_SYS", str(tmp_path))
    assert host_telemetry._devfreq_gpu_mhz() == (300, 1000)
    (gpu / "max_freq").write_text("?\n")
    assert host_telemetry._devfreq_gpu_mhz() == (300, 0)
    (gpu / "cur_freq").write_text("?\n")
    assert host_telemetry._devfreq_gpu_mhz() == (0, 0)
