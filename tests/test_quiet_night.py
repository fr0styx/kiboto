"""Quieter at night (hardware extra, off by default): the drive fans' curve is read a few degrees
lower between two times; warm drives, the full-speed override and the fixed modes are untouched."""

import datetime as dt
import importlib

import pytest


@pytest.fixture
def qn(monkeypatch, tmp_path):
    # the module the fan loop imports now: a test elsewhere may have reloaded it (random order, seed 652131)
    module = importlib.import_module("backend.services.quiet_night")
    monkeypatch.setattr(module, "SETTINGS_FILE", str(tmp_path / "qn.json"))
    return module


NIGHT = dt.datetime(2026, 11, 18, 2, 30)
DAY = dt.datetime(2026, 11, 18, 14, 0)


def test_off_by_default(qn):
    st = qn.public_state(NIGHT)
    assert st["enabled"] is False and st["start"] == "23:00" and st["end"] == "07:00" and st["active_now"] is False
    assert qn.curve_temp(40, NIGHT) == 40


def test_at_night_the_curve_reads_cooler(qn):
    qn.save(True, "23:00", "07:00")
    assert qn.curve_temp(40, NIGHT) == 36
    assert qn.curve_temp(40, DAY) == 40
    assert qn.public_state(NIGHT)["active_now"] is True


def test_warm_drives_get_the_normal_curve(qn):
    assert qn.shift_for(30) == 4 and qn.shift_for(45) == 4
    assert qn.shift_for(47.5) == pytest.approx(2)
    assert qn.shift_for(50) == 0 and qn.shift_for(58) == 0
    qn.save(True, "00:00", "23:59")
    assert qn.curve_temp(52, dt.datetime(2026, 11, 18, 12, 0)) == 52


def test_windows_across_and_within_a_day(qn):
    assert qn.in_window(dt.datetime(2026, 1, 1, 23, 0), "23:00", "07:00")
    assert qn.in_window(dt.datetime(2026, 1, 1, 6, 59), "23:00", "07:00")
    assert not qn.in_window(dt.datetime(2026, 1, 1, 7, 0), "23:00", "07:00")
    assert qn.in_window(dt.datetime(2026, 1, 1, 13, 0), "12:00", "14:00")
    assert not qn.in_window(dt.datetime(2026, 1, 1, 14, 0), "12:00", "14:00")


def test_refusals_and_bad_stored_times(qn):
    from backend.errors import SaidError
    from backend.fsutil import atomic_write_json

    with pytest.raises(SaidError):
        qn.save(True, "11pm", "07:00")
    with pytest.raises(SaidError):
        qn.save(True, "07:00", "07:00")
    atomic_write_json(qn.SETTINGS_FILE, {"enabled": True, "start": "nonsense", "end": 7})
    st = qn.state()
    assert st["start"] == "23:00" and st["end"] == "07:00"
    assert qn.active(NIGHT) is True


def test_the_fan_loop_reads_the_shifted_curve_only_in_automatic(qn, monkeypatch):
    from backend.services import fan_control

    seen = []

    def fake_curve(temp, **kw):
        seen.append((kw.get("zone_key"), temp))
        return 100

    monkeypatch.setattr(fan_control, "calc_curve_pwm", fake_curve)
    qn.save(True, "00:00", "23:59")
    assert (fan_control._drive_curve_temp(40, "auto"), fan_control._drive_curve_temp(41, "auto")) == (36, 37)
    assert fan_control._drive_curve_temp(40, "quiet") == 40
    qn.save(False, "00:00", "23:59")
    assert fan_control._drive_curve_temp(40, "auto") == 40


def test_the_routes(client, auth_headers, qn):
    r = client.get("/api/fans/quiet-night", headers=auth_headers)
    assert r.status_code == 200 and r.json()["enabled"] is False
    r = client.put(
        "/api/fans/quiet-night", headers=auth_headers, json={"enabled": True, "start": "22:30", "end": "06:30"}
    )
    assert r.status_code == 200 and r.json()["start"] == "22:30"
    r = client.put("/api/fans/quiet-night", headers=auth_headers, json={"enabled": True, "start": "x", "end": "06:30"})
    assert r.status_code == 400 and r.json()["text"]["msg_key"] == "srv.qn_times"
