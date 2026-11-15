"""The family sign-in for other apps follows every change to the people (SET-19)."""

import pytest

from backend import users_db


class FakeTimer:
    made: list["FakeTimer"] = []

    def __init__(self, secs, fn):
        self.secs, self.fn, self.cancelled = secs, fn, False
        FakeTimer.made.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def heard(monkeypatch):
    calls = []
    FakeTimer.made = []
    monkeypatch.setattr(users_db, "test_mode", lambda: False)
    monkeypatch.setattr(users_db.threading, "Timer", FakeTimer)
    monkeypatch.setattr(users_db, "_PEOPLE_HOOKS", [lambda: calls.append(1)])
    monkeypatch.setattr(users_db, "_people_timer", None)
    monkeypatch.setattr("backend.services.samba_engine.refresh_access", lambda: None)
    return calls


def _fire():
    live = [t for t in FakeTimer.made if not t.cancelled]
    assert len(live) == 1, live
    live[0].fn()


def test_adding_renaming_and_removing_are_heard_once_each_batch(heard):
    user = users_db.create_user("pf_ada", "Ada", "Some-Pass-12345", role_id="kid")
    users_db.update_user_profile(user["id"], display_name="Ada L.")
    _fire()  # two changes, one call
    assert heard == [1]
    FakeTimer.made = []
    users_db.delete_user(user["id"])
    _fire()
    assert heard == [1, 1]


def test_quota_or_hours_alone_are_not_a_change_for_other_apps(heard):
    user = users_db.create_user("pf_bo", "Bo", "Some-Pass-12345", role_id="kid")
    FakeTimer.made = []
    users_db.update_user_profile(user["id"], storage_quota_bytes=5)
    assert FakeTimer.made == []


def test_a_failing_service_is_logged_not_raised(monkeypatch, heard):
    def broken():
        raise RuntimeError("pocket id down")

    monkeypatch.setattr(users_db, "_PEOPLE_HOOKS", [broken])
    users_db._run_people_hooks()  # no exception


def test_nothing_runs_in_tests_or_without_listeners(monkeypatch):
    monkeypatch.setattr(users_db, "_PEOPLE_HOOKS", [])
    users_db._people_changed()
    monkeypatch.setattr(users_db, "_PEOPLE_HOOKS", [lambda: None])
    users_db._people_changed()  # test mode: nothing scheduled
    assert users_db._people_timer is None or users_db._people_timer.daemon


def test_the_app_registers_the_family_sign_in(monkeypatch):
    import backend.main as main

    synced = []
    monkeypatch.setattr("backend.services.family_signin.config", lambda: {"enabled": True})
    monkeypatch.setattr("backend.services.family_signin.sync", lambda actor="": synced.append(actor))
    main._family_signin_follows_people()
    assert synced == ["people change"]
    monkeypatch.setattr("backend.services.family_signin.config", lambda: {"enabled": False})
    main._family_signin_follows_people()
    assert synced == ["people change"]
