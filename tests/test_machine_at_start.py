"""At each start on a managed host: the packages this version needs, then the drive sleep timers."""

from backend import main
from backend.services import drive_sleep, native_update


def test_the_tools_come_first_then_the_timers(monkeypatch):
    done = []
    monkeypatch.setattr(native_update, "add_missing_tools", lambda rel: done.append(("tools", rel)) or [])
    monkeypatch.setattr(native_update, "ensure_units", lambda rel: done.append(("units", rel)) or [])
    monkeypatch.setattr(drive_sleep, "at_start", lambda: done.append(("timers",)) or [{"drive": "sdb", "state": "set"}])
    main._machine_at_start()
    assert done == [("tools", "/opt/kiboto/current"), ("units", "/opt/kiboto/current"), ("timers",)]


def test_a_failure_of_either_is_said_and_the_other_still_runs(monkeypatch, caplog):
    def broken(*a):
        raise OSError("no apt")

    timers = []
    monkeypatch.setattr(native_update, "add_missing_tools", broken)
    monkeypatch.setattr(drive_sleep, "at_start", lambda: timers.append(1) or [])
    main._machine_at_start()
    assert timers == [1] and "were not checked" in caplog.text
    monkeypatch.setattr(native_update, "add_missing_tools", lambda rel: [])
    monkeypatch.setattr(native_update, "ensure_units", lambda rel: [])
    monkeypatch.setattr(drive_sleep, "at_start", lambda: (_ for _ in ()).throw(ValueError("x")))
    main._machine_at_start()
    assert "were not set" in caplog.text
