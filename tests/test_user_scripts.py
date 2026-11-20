"""Scheduled scripts (owner's decision, 19 Nov 2026): off by default, the full administrator only,
every run on record. The folder limit itself is tried on a real system (it needs the right to make
a mount namespace, which a test runner does not have); here the command it builds is read."""

import os
import time

import pytest

from backend.services import user_scripts as us

MONDAY_0330 = time.mktime((2026, 11, 16, 3, 30, 0, 0, 0, -1))


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(us, "STATE_FILE", str(tmp_path / "scripts.json"))
    monkeypatch.setattr(us, "RUNS_FILE", str(tmp_path / "runs.json"))
    monkeypatch.setattr(us, "WORK_DIR", str(tmp_path))
    share = tmp_path / "share"
    share.mkdir()
    monkeypatch.setattr(us, "ALLOWED_BROWSE_ROOTS", [str(share)])
    us.reset_for_tests()
    yield share
    for sid in list(us.running()):
        us.stop(sid)
    us.reset_for_tests()


def _script(**over):
    return {"name": "Tidy up", "body": "echo hello\n", "schedule": {"kind": "manual"}, **over}


def _wait(sid, seconds=20.0):
    end = time.time() + seconds
    while time.time() < end:
        if sid not in us.running() and us.last_run(sid):
            return us.last_run(sid)
        time.sleep(0.05)
    raise AssertionError("the run did not end")


def test_off_until_turned_on_and_nothing_runs_while_off():
    assert us.enabled() is False and us.scripts() == []
    made = us.save(_script(schedule={"kind": "hourly", "minute": 30}))
    with pytest.raises(us.NotNow) as refused:
        us.start(made["id"], "by_hand", "ana")
    assert refused.value.key == "off"
    assert us.run_due(MONDAY_0330) == []  # due this minute, and off
    assert us.set_enabled(True) is True and us.enabled() is True
    assert us.run_due(MONDAY_0330) == [made["id"]]
    assert us.run_due(MONDAY_0330) == []  # once per minute
    assert _wait(made["id"])["how"] == "schedule"


def test_what_a_script_may_be(fresh):
    ok = us.clean(_script(name="  Night   copy ", body="a\r\nb", timeout_min=5, limit_folder=str(fresh)))
    assert (ok["name"], ok["body"], ok["limit_folder"], ok["timeout_min"]) == ("Night copy", "a\nb", str(fresh), 5)
    assert ok["schedule"] == {"kind": "manual"} and ok["enabled"] is True
    for change, key in [
        ({"name": ""}, "bad_name"),
        ({"name": "x" * 61}, "bad_name"),
        ({"body": "  \n"}, "empty"),
        ({"body": "a\x00b"}, "too_long"),
        ({"body": "x" * (us.MAX_BODY_BYTES + 1)}, "too_long"),
        ({"timeout_min": 0}, "bad_timeout"),
        ({"timeout_min": us.MAX_TIMEOUT_MIN + 1}, "bad_timeout"),
        ({"timeout_min": True}, "bad_timeout"),
        ({"schedule": {"kind": "yearly"}}, "bad_schedule"),
        ({"schedule": {"kind": "daily", "at": "25:00"}}, "bad_time"),
        ({"schedule": {"kind": "hourly", "minute": 60}}, "bad_time"),
        ({"schedule": {"kind": "weekly", "at": "03:30", "days": []}}, "no_days"),
        ({"schedule": {"kind": "weekly", "at": "03:30", "days": [7, True]}}, "no_days"),
        ({"limit_folder": "/etc"}, "bad_folder"),
        ({"limit_folder": str(fresh / "missing")}, "bad_folder"),
    ]:
        with pytest.raises(us.ScriptError) as bad:
            us.clean(_script(**change))
        assert bad.value.key == key, change
    with pytest.raises(us.ScriptError) as bad:
        us.clean(_script(name=""))
    assert bad.value.params == {"value": us.MAX_NAME}
    weekly = us.clean(_script(schedule={"kind": "weekly", "at": "03:30", "days": [6, 0, 0]}))
    assert weekly["schedule"] == {"kind": "weekly", "at": "03:30", "days": [0, 6]}


def test_a_folder_inside_kibotos_own_data_cannot_be_the_limit(fresh, monkeypatch):
    inside = fresh / "appdata" / "kiboto"
    inside.mkdir(parents=True)
    monkeypatch.setattr(us, "DATA_DIR", str(fresh / "appdata"))
    for folder in (fresh / "appdata", inside):
        with pytest.raises(us.ScriptError):
            us.clean(_script(limit_folder=str(folder)))
    assert us.clean(_script(limit_folder=str(fresh)))["limit_folder"] == str(fresh)  # the share around it may


def test_add_change_delete_and_the_most_there_can_be():
    a = us.save(_script())
    assert us.get(a["id"])["name"] == "Tidy up" and a["created"]
    b = us.save(_script(name="Changed", body="echo 2"), a["id"])
    assert b["id"] == a["id"] and b["created"] == a["created"] and us.get(a["id"])["body"] == "echo 2"
    with pytest.raises(KeyError):
        us.save(_script(), "nope")
    for i in range(us.MAX_SCRIPTS - 1):
        us.save(_script(name=f"s{i}"))
    with pytest.raises(us.ScriptError) as full:
        us.save(_script(name="one too many"))
    assert full.value.key == "too_many" and full.value.params == {"value": us.MAX_SCRIPTS}
    assert us.delete(a["id"]) is True and us.delete(a["id"]) is False and us.get(a["id"]) is None


def test_a_run_is_recorded_with_how_it_ended(monkeypatch):
    logged = []
    from backend import users_db

    monkeypatch.setattr(users_db, "log_security_event", lambda event, status, **k: logged.append((event, status, k)))
    us.set_enabled(True)
    good = us.save(_script(body="echo one; echo two >&2; echo $KIBOTO_SCRIPT; pwd"))
    assert set(us.start(good["id"], "by_hand", "ana")) == {"started"}
    run = _wait(good["id"])
    assert run["ok"] and run["exit_code"] == 0 and (run["how"], run["who"]) == ("by_hand", "ana")
    assert run["output"] == "one\ntwo\nTidy up\n/\n" and run["output_bytes"] == len(run["output"])
    bad = us.save(_script(name="Fails", body="#!/bin/sh\necho no; exit 3"))
    us.start(bad["id"], "by_hand", "ana")
    run = _wait(bad["id"])
    assert not run["ok"] and run["exit_code"] == 3 and run["output"] == "no\n"
    assert [(e, s, k["details"]["script"], k["details"]["exit_code"]) for e, s, k in logged] == [
        ("scripts.run", "success", "Tidy up", 0),
        ("scripts.run", "failure", "Fails", 3),
    ]
    assert logged[0][2]["actor_username"] == "ana" and logged[0][2]["details"]["how"] == "by_hand"
    assert len(us.runs(bad["id"])) == 1 and us.runs("nope") == []
    us.delete(bad["id"])
    assert us.runs(bad["id"]) == []  # the record goes with the script


def test_only_the_end_of_long_output_is_kept_and_only_so_many_runs(monkeypatch):
    monkeypatch.setattr(us, "OUTPUT_KEPT_BYTES", 200)
    monkeypatch.setattr(us, "RUNS_KEPT", 3)
    us.set_enabled(True)
    loud = us.save(_script(body="i=0; while [ $i -lt 400 ]; do echo line-$i; i=$((i+1)); done"))
    for _ in range(4):
        us.start(loud["id"], "by_hand")
        run = _wait(loud["id"])
        time.sleep(0.02)
    assert len(run["output"]) <= 200 and run["output"].endswith("line-399\n") and run["output_bytes"] > 3000
    assert len(us.runs(loud["id"])) == 3


def test_a_time_limit_a_stop_and_one_run_at_a_time(monkeypatch):
    us.set_enabled(True)
    slow = us.save(_script(name="Slow", body="echo start; sleep 30; echo never"))
    us.start(slow["id"], "by_hand", "ana")
    with pytest.raises(us.NotNow) as twice:
        us.start(slow["id"], "by_hand", "ana")
    assert twice.value.key == "running"
    end = time.time() + 5
    while not us.stop(slow["id"]) and time.time() < end:  # the process may not have started yet
        time.sleep(0.05)
    run = _wait(slow["id"])
    assert run["stopped"] and not run["ok"] and "never" not in run["output"]
    assert us.stop(slow["id"]) is False  # nothing is going any more

    limited = us.save(_script(name="Late", body="sleep 30"))
    monkeypatch.setattr(us, "DEFAULT_TIMEOUT_MIN", 0)  # no time at all, for the test
    stored = us.get(limited["id"])
    stored["timeout_min"] = 0
    us._run(stored, {"started": time.time(), "how": "schedule", "who": ""})
    run = us.last_run(limited["id"])
    assert run["timed_out"] and not run["ok"] and not run["stopped"]


def test_too_many_at_once_and_a_scheduled_failure_is_an_alert(monkeypatch):
    events = []
    monkeypatch.setattr(
        "backend.state.add_event", lambda level, title, msg, details=None: events.append((level, details))
    )
    monkeypatch.setattr(us, "MAX_AT_ONCE", 1)
    us.set_enabled(True)
    slow = us.save(_script(name="Slow", body="sleep 30"))
    other = us.save(_script(name="Other", body="exit 4", schedule={"kind": "daily", "at": "03:30"}))
    us.start(slow["id"], "by_hand")
    with pytest.raises(us.NotNow) as busy:
        us.start(other["id"], "by_hand")
    assert busy.value.key == "busy"
    assert us.run_due(MONDAY_0330) == []  # due, and said in the log instead of started
    end = time.time() + 5
    while not us.stop(slow["id"]) and time.time() < end:
        time.sleep(0.05)
    _wait(slow["id"])
    assert events == []  # a run by hand that ends badly is on the screen already
    us._FIRED.clear()
    assert us.run_due(MONDAY_0330) == [other["id"]]
    _wait(other["id"])
    assert events[0][0] == "warning" and events[0][1]["msg_key"] == "ev.script_failed_code.msg"
    assert events[0][1]["params"] == {"name": "Other", "code": 4}


def test_schedules_name_their_minutes():
    t = time.localtime(MONDAY_0330)

    def s(kind, enabled=True, **more):
        return {"enabled": enabled, "schedule": {"kind": kind, **more}}

    assert us.due(s("hourly", minute=30), t) and not us.due(s("hourly", minute=31), t)
    assert us.due(s("daily", at="03:30"), t) and not us.due(s("daily", at="03:31"), t)
    assert us.due(s("weekly", at="03:30", days=[0]), t) and not us.due(s("weekly", at="03:30", days=[1, 6]), t)
    assert not us.due(s("manual"), t) and not us.due(s("daily", enabled=False, at="03:30"), t)
    assert us.next_run(s("daily", at="03:30"), MONDAY_0330) == MONDAY_0330 + 86400
    assert us.next_run(s("hourly", minute=45), MONDAY_0330) == MONDAY_0330 + 900
    assert us.next_run(s("weekly", at="03:30", days=[2]), MONDAY_0330) == MONDAY_0330 + 2 * 86400
    assert us.next_run(s("manual"), MONDAY_0330) is None and us.next_run(s("daily", enabled=False, at="03:30")) is None


def test_the_command_for_a_script_limited_to_a_folder(fresh, monkeypatch):
    plain = us.command({"body": "echo hi", "limit_folder": ""}, "/var/tmp/x/script")
    assert plain[-1] == "/var/tmp/x/script" and os.path.basename(plain[0]) in ("bash", "sh")
    assert us.command({"body": "#!/usr/bin/env python3\nprint(1)", "limit_folder": ""}, "/p") == ["/p"]
    limited = us.command({"body": "echo hi", "limit_folder": str(fresh)}, "/var/tmp/x/script")
    assert limited[:8] == ["unshare", "--mount", "--pid", "--fork", "--mount-proc", "--propagation", "private", "--"]
    assert limited[8:10] == ["sh", "-c"] and limited[10] == us.LIMIT_WRAP
    assert limited[12:14] == [str(fresh), os.path.realpath(us.DATA_DIR)] and limited[-1] == "/var/tmp/x/script"
    wrap = us.LIMIT_WRAP
    # what the limit rests on, in the order it must happen
    steps = [
        'mount --bind "$F" "$F"',
        "tmpfs /tmp",
        'tmpfs "$DATA"',
        "tmpfs /dev",
        "docker.sock",
        "remount,bind,ro",
        "exec setpriv",
    ]
    places = [wrap.index(step) for step in steps]
    assert places == sorted(places)
    assert "+sys_admin" not in wrap and "--no-new-privs" in wrap and "exit 97" in wrap


def test_a_limited_script_is_not_started_where_the_limit_cannot_be_made(fresh, monkeypatch):
    us.set_enabled(True)
    made = us.save(_script(limit_folder=str(fresh)))
    asked = []
    monkeypatch.setattr(us.shutil, "which", lambda name: asked.append(name))
    now = time.time()
    assert us.limit_available(now=now) is False and asked
    asked.clear()
    assert us.limit_available(now=now + 100) is False and not asked  # asked again only after ten minutes
    with pytest.raises(us.NotNow) as refused:
        us.start(made["id"], "by_hand")
    assert refused.value.key == "no_limit" and us.runs(made["id"]) == []

    class Done:
        returncode = 0

    monkeypatch.setattr(us.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(us.subprocess, "run", lambda *a, **k: Done())
    assert us.limit_available(now=time.time() + 1000) is True

    def refuses(*a, **k):
        raise OSError("not permitted")

    monkeypatch.setattr(us.subprocess, "run", refuses)
    assert us.limit_available(now=time.time() + 2000) is False


def test_a_run_counts_as_running_until_its_result_is_on_record(monkeypatch):
    """Found in a real browser: for a moment a finished run was neither running nor on record,
    and a screen that looks again only while something runs stopped looking."""
    us.set_enabled(True)
    made = us.save(_script())
    seen = []
    real = us._note_run

    def note(script_id, run):
        seen.append((script_id in us.running(), us.last_run(script_id)))
        real(script_id, run)
        seen.append((script_id in us.running(), bool(us.last_run(script_id))))

    monkeypatch.setattr(us, "_note_run", note)
    us.start(made["id"], "by_hand")
    _wait(made["id"])
    assert seen == [(True, None), (True, True)]
    assert made["id"] not in us.running()


def test_a_minute_the_scheduler_never_looked_at_still_starts_the_script(fresh, monkeypatch):
    started = []
    monkeypatch.setattr(us, "start", lambda sid, how, who="": started.append((sid, how)) or {"started": 0})
    us.set_enabled(True)
    daily = us.save(_script(name="Nightly", body="true", schedule={"kind": "daily", "at": "03:30"}))
    hourly = us.save(_script(name="Hourly", body="true", schedule={"kind": "hourly", "minute": 30}))
    weekly = us.save(_script(name="Tuesdays", body="true", schedule={"kind": "weekly", "at": "03:30", "days": [1]}))
    us._FIRED.clear()
    assert us.run_due(MONDAY_0330 - 5) == []
    assert sorted(us.run_due(MONDAY_0330 + 65)) == sorted([daily["id"], hourly["id"]])  # looked at 03:31, not 03:30
    assert us.run_due(MONDAY_0330 + 125) == []  # once for that minute
    assert us.run_due(MONDAY_0330 + 3600 + 70) == [hourly["id"]]
    assert us.run_due(MONDAY_0330 + 86400 + 200) and weekly["id"] in [s for s, _ in started]
    # after a restart nothing is remembered in memory: the run that was noted is not started again
    us._FIRED.clear()
    started.clear()
    monkeypatch.setattr(us, "last_run", lambda sid: {"started": MONDAY_0330 + 2 * 86400 + 4, "how": "schedule"})
    assert us.run_due(MONDAY_0330 + 2 * 86400 + 90) == [] and started == []
    us._FIRED.clear()
    monkeypatch.setattr(us, "last_run", lambda sid: {"started": MONDAY_0330 + 2 * 86400 + 4, "how": "by_hand"})
    assert daily["id"] in us.run_due(MONDAY_0330 + 2 * 86400 + 90)  # a run by hand is not the night's run
