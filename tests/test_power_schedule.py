"""Audit A10: scheduled power off with an RTC wake-up, off by default, never off without a wake-up."""

import datetime as dt

import pytest

from backend.services import power_schedule as ps


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "STATE_FILE", str(tmp_path / "ps.json"))
    rtc = tmp_path / "wakealarm"
    rtc.write_text("")
    monkeypatch.setattr(ps, "RTC_PATHS", (str(rtc),))
    monkeypatch.setattr(ps, "_tell", lambda *a, **k: None)
    return rtc


NIGHT = dt.datetime(2026, 11, 16, 1, 0, 30)  # a Monday 01:00


def test_off_by_default_and_settings_that_cannot_work_are_refused(monkeypatch):
    st = ps.public_state()
    assert st["enabled"] is False and st["wake_possible"] is True
    with pytest.raises(ValueError, match="like 01:00"):
        ps.save(True, "1am", "07:00", [0])
    with pytest.raises(ValueError, match="must differ"):
        ps.save(True, "07:00", "07:00", [0])
    with pytest.raises(ValueError, match="at least one night"):
        ps.save(True, "01:00", "07:00", [])
    monkeypatch.setattr(ps, "RTC_PATHS", ("/nonexistent/wakealarm",))
    with pytest.raises(ValueError, match="wake-up clock"):
        ps.save(True, "01:00", "07:00", [0])
    assert ps.save(False, "23:30", "06:45", [9, 1, 1, 0])["days"] == [0, 1]


def test_switches_off_once_after_setting_and_checking_the_wake_up(_state):
    ps.save(True, "01:00", "07:00", list(range(7)))
    offs = []
    assert ps.tick(NIGHT, busy=lambda: "", power_off=lambda: offs.append(1) or True) == "off"
    woke = dt.datetime.fromtimestamp(int(_state.read_text()))
    assert (woke.hour, woke.minute, woke.date()) == (7, 0, NIGHT.date())
    assert offs == [1] and ps.state()["last_off"] == "2026-11-15"
    assert ps.tick(NIGHT + dt.timedelta(minutes=2), busy=lambda: "", power_off=lambda: offs.append(2) or True) == ""
    assert offs == [1]


def test_never_off_without_a_wake_up(monkeypatch):
    ps.save(True, "01:00", "07:00", list(range(7)))
    offs = []
    assert (
        ps.tick(NIGHT, busy=lambda: "", wake=lambda w, p: False, power_off=lambda: offs.append(1) or True) == "no_wake"
    )
    assert offs == [] and ps.state()["last_note"] == "no_wake"


def test_a_busy_nas_waits_up_to_two_hours_then_switches_off():
    ps.save(True, "01:00", "07:00", list(range(7)))
    t = NIGHT
    for _ in range(4):
        assert ps.tick(t, busy=lambda: "job", power_off=lambda: True) == "postponed"
        t += dt.timedelta(minutes=30)
    assert ps.state()["postponed_min"] == 120
    assert ps.tick(t, busy=lambda: "job", power_off=lambda: True) == "off"


def test_only_on_chosen_nights_and_at_the_time():
    ps.save(True, "23:30", "07:00", [6])  # Sunday nights only
    sunday = dt.datetime(2026, 11, 15, 23, 30, 10)
    monday = dt.datetime(2026, 11, 16, 23, 30, 10)
    assert ps.tick(monday, busy=lambda: "", power_off=lambda: True) == ""
    assert ps.tick(sunday - dt.timedelta(minutes=1), busy=lambda: "", power_off=lambda: True) == ""
    assert ps.tick(sunday, busy=lambda: "", power_off=lambda: True) == "off"
    ps.save(False, "23:30", "07:00", [6])
    assert ps.tick(sunday + dt.timedelta(days=7), busy=lambda: "", power_off=lambda: True) == ""


def test_a_failed_power_off_is_noted_and_the_wake_up_is_set_for_the_next_morning():
    ps.save(True, "01:00", "07:00", list(range(7)))
    assert ps.tick(NIGHT, busy=lambda: "", power_off=lambda: False) == "failed"
    assert ps.state()["last_note"] == "failed"
    late = dt.datetime(2026, 11, 16, 6, 55)
    assert ps.next_wake(late, "07:00").date() == dt.date(2026, 11, 17)
    assert ps.loop_once() == ""


def test_routes(client, auth_headers):
    assert client.get("/api/system/power-schedule", headers=auth_headers).json()["enabled"] is False
    bad = client.put(
        "/api/system/power-schedule", headers=auth_headers, json={"enabled": True, "off_at": "1", "wake_at": "07:00"}
    )
    assert bad.status_code == 400
    ok = client.put(
        "/api/system/power-schedule",
        headers=auth_headers,
        json={"enabled": True, "off_at": "00:30", "wake_at": "06:30", "days": [5, 6]},
    )
    assert ok.status_code == 200 and ok.json()["days"] == [5, 6]


def test_without_a_shutdown_passed_in_it_does_not_switch_off():
    ps.save(True, "01:00", "07:00", list(range(7)))
    assert ps.tick(NIGHT, busy=lambda: "") == "failed"
    assert ps.state()["last_note"] == "failed"
