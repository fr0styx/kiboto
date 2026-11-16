"""Settings decision 5: the daily update check announces each new version once, can be turned off,
and records failed checks without announcing."""

import asyncio

import pytest

from backend.api import update_watch as api_watch
from backend.services import update_watch


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(update_watch, "STATE_FILE", str(tmp_path / "update_watch.json"))


def test_due_once_a_day_and_not_when_off():
    assert update_watch.due(100_000.0)
    update_watch.record({"update_available": False}, 100_000.0)
    assert not update_watch.due(100_000.0 + 3600)
    assert update_watch.due(100_000.0 + 86_400)
    update_watch.set_daily(False)
    assert not update_watch.due(1e9)


def test_each_version_is_announced_once():
    assert update_watch.record({"update_available": True, "latest_version": "2.0.4"}, 1.0) == "2.0.4"
    assert update_watch.record({"update_available": True, "latest_version": "2.0.4"}, 2.0) == ""
    assert update_watch.state()["available"] is True
    assert update_watch.record({"update_available": True, "latest_version": "2.0.5"}, 3.0) == "2.0.5"
    assert update_watch.record({"update_available": False}, 4.0) == ""
    assert update_watch.state()["available"] is False
    assert update_watch.record({"error": "GitHub API HTTP 503"}, 5.0) == ""
    assert update_watch.state()["last_check"] == 5.0


def test_check_once_announces_and_survives_a_failed_check(monkeypatch):
    sent = []
    monkeypatch.setattr(api_watch, "_announce", lambda v: sent.append(v))

    import backend.api.system as system

    async def ready(force=False, channel="stable"):
        return {"update_available": True, "latest_version": "2.0.9"}

    monkeypatch.setattr(system, "check_system_updates", ready)
    assert asyncio.run(api_watch.check_once(10.0)) == "2.0.9"
    assert sent == ["2.0.9"]

    async def broken(force=False, channel="stable"):
        raise OSError("no network")

    monkeypatch.setattr(system, "check_system_updates", broken)
    assert asyncio.run(api_watch.check_once(20.0)) == ""
    assert sent == ["2.0.9"]


def test_the_routes_read_and_switch():
    assert api_watch.get_update_watch()["daily"] is True
    assert api_watch.put_update_watch(api_watch.UpdateWatchIn(daily=False))["daily"] is False
    assert api_watch.get_update_watch()["daily"] is False


def test_the_alert_is_sent_in_the_households_words(monkeypatch):
    import backend.services.notifications as notifications

    calls = []
    monkeypatch.setattr(notifications, "send_notification", lambda **kw: calls.append(kw))
    api_watch._announce("2.0.4")
    assert calls[0]["text"]["msg_key"] == "alert.update_ready.msg" and calls[0]["dedup_key"] == "kiboto-update-2.0.4"
