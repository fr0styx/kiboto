"""Backup A16: a missed day is caught up once; a failed backup is not started again every minute."""

import time

from backend.services import offsite_backup as ob


def _at(hour, day=16):
    return time.mktime((2026, 11, day, hour, 5, 0, 0, 0, -1))


def test_due_at_its_hour_and_not_twice():
    now = _at(2)
    repo = {"hour": 2, "last_backup": now - 24 * 3600}
    assert ob.backup_due(repo, now)
    assert not ob.backup_due({**repo, "last_attempt": now - 60}, now)  # tried a minute ago: wait
    assert ob.backup_due({**repo, "last_attempt": now - 2 * 3600}, now)
    assert not ob.backup_due({**repo, "last_backup": now - 3600}, now)  # done tonight already


def test_a_missed_day_is_caught_up_but_a_first_backup_waits_for_its_hour():
    now = _at(9)
    assert ob.backup_due({"hour": 2, "last_backup": now - 30 * 3600}, now)  # the NAS was off at 02:00
    assert not ob.backup_due({"hour": 2, "last_backup": now - 10 * 3600}, now)
    assert not ob.backup_due({"hour": 2, "last_backup": 0}, now)
    assert not ob.backup_due({"hour": 2, "last_backup": now - 30 * 3600, "last_attempt": now - 1800}, now)


def test_run_due_marks_the_try_before_it_starts(monkeypatch):
    now = _at(2)
    repos = [{"id": "usb", "hour": 2, "last_backup": now - 24 * 3600}, {"id": "off", "hour": None}]
    marks, starts = [], []
    monkeypatch.setattr(ob, "list_repos", lambda: repos)
    monkeypatch.setattr(ob, "_update", lambda rid, **f: marks.append((rid, f)))

    class _T:
        def __init__(self, target, args, daemon, name):
            starts.append(name)

        def start(self):
            pass

    monkeypatch.setattr(ob.threading, "Thread", _T)
    assert ob.run_due(now) == ["usb"]
    assert marks == [("usb", {"last_attempt": now})] and starts == ["offsite-usb"]
