"""SET-31, Power stage 3: the whole answer of the Power page from one reading."""

import json
import time

import pytest

from backend.services import power_comes_back
from backend.services import power_summary as ps

CFG = {
    "shutdown_policy": "runtime_left",
    "runtime_threshold_min": 5,
    "battery_threshold_pct": 20,
    "shutdown_timer_sec": 300,
}
OK_PATH = {"by": "kiboto", "ok": True, "text": None, "detail": "Kiboto shuts the server down with /host/powerdown."}
NO_PATH = {"by": "kiboto", "ok": False, "detail": "Kiboto has no way to shut this server down."}
QUIET = {"since": None, "drill": False, "failsafe": False, "silent": False}


def ups(**kw):
    base = {
        "available": True,
        "status": "OL",
        "battery_charge_pct": 100.0,
        "time_left_min": 31.0,
        "on_battery": False,
        "battery_low": False,
    }
    return {**base, **kw}


@pytest.mark.parametrize(
    "reading,path,outage,state,reason",
    [
        ({"available": False}, OK_PATH, QUIET, "none", ""),
        ({"available": False, "unreadable": True}, OK_PATH, QUIET, "unreadable", ""),
        ({"available": True, "permission_error": True}, OK_PATH, QUIET, "unreadable", "permission"),
        (ups(), OK_PATH, QUIET, "protected", ""),
        (ups(), NO_PATH, QUIET, "look", "switch_off"),
        (ups(status="OL RB"), OK_PATH, QUIET, "look", "battery"),
        (ups(status="OL LB", battery_low=True), OK_PATH, QUIET, "look", "battery"),
        (
            ups(status="OB", on_battery=True, time_left_min=20.0),
            OK_PATH,
            {**QUIET, "since": time.time() - 60},
            "cut",
            "",
        ),
        (
            ups(status="OB", on_battery=True, time_left_min=3.0),
            OK_PATH,
            {**QUIET, "since": time.time() - 60},
            "shutting",
            "",
        ),
        (ups(status="OB LB", on_battery=True, battery_low=True), NO_PATH, QUIET, "by_hand", ""),
        (ups(status="OB", on_battery=True), OK_PATH, {**QUIET, "failsafe": True}, "shutting", ""),
        ({"available": False}, OK_PATH, {**QUIET, "silent": True, "since": 1.0}, "silent", ""),
    ],
)
def test_one_state_from_one_reading(reading, path, outage, state, reason):
    assert ps.state_of(reading, path, outage, CFG) == (state, reason)


def test_the_four_checks():
    c = {x["id"]: x for x in ps.checks(ups(status="OL RB", battery_charge_pct=None, time_left_min=None), NO_PATH)}
    assert c["readable"]["ok"] and not c["switch_off"]["ok"]
    assert not c["battery"]["ok"] and c["battery"]["replace"]
    assert c["rule"]["ok"] and c["rule"]["blind"]  # falls back to the set time, so it always fires


def test_starts_again_by_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(power_comes_back, "COMES_BACK_FILE", str(tmp_path / "back.json"))
    assert ps.comes_back("unraid") == {"answer": "host", "host": "Unraid"}
    assert ps.comes_back("kiboto") == {"answer": "not_proven"}
    (tmp_path / "back.json").write_text(json.dumps({"proven_at": 1700000000}))
    assert ps.comes_back("kiboto") == {"answer": "proven", "at": 1700000000}
    (tmp_path / "back.json").write_text(json.dumps({"failed_at": 1700000001}))
    assert ps.comes_back("kiboto") == {"answer": "no", "at": 1700000001}


def test_the_whole_answer(monkeypatch, tmp_path):
    monkeypatch.setattr(power_comes_back, "COMES_BACK_FILE", str(tmp_path / "back.json"))
    monkeypatch.setattr("backend.services.ups_watchdog.last_practice", lambda: {"at": 1, "ok": True})
    events = [{"ts": i, "event_type": "outage"} for i in range(7)]
    s = ps.summary(
        ups=ups(mode="nut_client", protocol="NUT", power_watts=80.0, nominal_power_watts=900.0),
        path=OK_PATH,
        outage=QUIET,
        cfg=CFG,
        events=events,
    )
    assert s["state"] == "protected" and s["numbers"] == {"battery_pct": 100.0, "minutes": 31.0, "watts": 80.0}
    assert s["switch_off"]["ok"] and s["rule"]["minutes"] == 5
    assert s["comes_back"] == {"answer": "not_proven"}
    assert s["tests"]["practice"] == {"at": 1, "ok": True}
    assert len(s["history"]) == 5
    assert s["can"] == {"self_test": True, "practice": True, "sockets": True}
    # watts only when the UPS reports its own rating; nothing is offered without a UPS
    s = ps.summary(ups={"available": False, "power_watts": 50.0}, path=OK_PATH, outage=QUIET, cfg=CFG, events=[])
    assert s["state"] == "none" and s["numbers"]["watts"] is None
    assert s["can"] == {"self_test": False, "practice": False, "sockets": False}


def test_the_watchdog_says_what_it_knows():
    from backend.services import ups_watchdog

    view = ups_watchdog.outage_view()
    assert set(view) == {"since", "drill", "failsafe", "silent"}


def test_route(client, auth_headers, monkeypatch):
    monkeypatch.setattr(ps, "summary", lambda: {"state": "none"})
    assert client.get("/api/power", headers=auth_headers).json() == {"state": "none"}


def test_who_switches_the_nas_off_is_asked_once_a_minute(monkeypatch):
    calls = []
    monkeypatch.setattr(ps, "_path_cache", {"at": 0.0, "value": None})

    def report():
        calls.append(1)
        return {"by": "kiboto", "ok": True}

    assert ps._path(report) == {"by": "kiboto", "ok": True}
    ps._path(report)
    assert len(calls) == 1


def test_the_last_battery_test_is_found_further_back(monkeypatch, tmp_path):
    monkeypatch.setattr(power_comes_back, "COMES_BACK_FILE", str(tmp_path / "back.json"))
    monkeypatch.setattr("backend.services.ups_watchdog.last_practice", lambda: {})
    events = [{"ts": 10 - i, "event_type": "OUTAGE_RECOVERED"} for i in range(6)]
    events.append({"ts": 2, "event_type": "SELF_TEST", "action_taken": "accepted"})
    s = ps.summary(ups=ups(), path=OK_PATH, outage=QUIET, cfg=CFG, events=events)
    assert s["tests"]["battery"] == {"at": 2, "text": "accepted"} and len(s["history"]) == 5
    s = ps.summary(ups=ups(), path=OK_PATH, outage=QUIET, cfg=CFG, events=[])
    assert s["tests"] == {"practice": None, "battery": None}


def test_one_question_after_a_real_power_cut(monkeypatch, tmp_path):
    """Power decision 6: "starts again by itself" is proven only by a real power cut, from one question."""
    monkeypatch.setattr(power_comes_back, "COMES_BACK_FILE", str(tmp_path / "back.json"))
    assert ps.ask_after_start() is False  # an ordinary start asks nothing
    ps.remember_power_cut(1700000000)
    ps.forget_power_cut()  # the host command failed: nothing was switched off
    assert ps.ask_after_start() is False
    ps.remember_power_cut(1700000000)
    assert ps.ask_after_start() is True
    assert ps.comes_back("kiboto") == {"answer": "ask", "at": 1700000000}
    assert ps.answer_comes_back(True) == {"answer": "proven", "at": 1700000000}
    with pytest.raises(ValueError):
        ps.answer_comes_back(True)  # asked once
    ps.remember_power_cut(1700000500)
    ps.ask_after_start()
    assert ps.answer_comes_back(False) == {"answer": "no", "at": 1700000500}


def test_the_answer_route(client, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(power_comes_back, "COMES_BACK_FILE", str(tmp_path / "back.json"))
    assert client.post("/api/power/comes-back", json={"by_itself": True}, headers=auth_headers).status_code == 409
    ps.remember_power_cut(1700000000)
    ps.ask_after_start()
    r = client.post("/api/power/comes-back", json={"by_itself": True}, headers=auth_headers)
    assert r.json() == {"answer": "proven", "at": 1700000000}


def test_the_safe_shutdown_remembers_the_cut_and_forgets_it_when_nothing_switched_off(monkeypatch, tmp_path):
    from backend.services import ups_watchdog

    monkeypatch.setattr(power_comes_back, "COMES_BACK_FILE", str(tmp_path / "back.json"))
    for name in (
        "_say_shutdown_starts",
        "nut_forced_shutdown",
        "_pause_copy",
        "_machines_first",
        "graceful_docker_teardown",
        "log_ups_event",
        "add_event",
    ):
        monkeypatch.setattr(ups_watchdog, name, lambda *a, **k: None)
    monkeypatch.setattr(ups_watchdog, "shutdown_owner", lambda: "kiboto")
    monkeypatch.setattr(ups_watchdog, "load_ups_config", lambda: {})
    monkeypatch.setattr(ups_watchdog, "signal_host_powerdown", lambda: True)
    monkeypatch.setattr(ups_watchdog, "_failsafe_engaged", False)
    monkeypatch.setattr(ups_watchdog, "_host_shutdown_started", False)
    ups_watchdog.execute_atomic_failsafe_shutdown(5, 2, "battery low")
    assert "cut_at" in json.loads((tmp_path / "back.json").read_text())
