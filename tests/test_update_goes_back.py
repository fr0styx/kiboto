"""An update must keep the app running: a new version that stops right after it starts sends
the app back to its old container (before, the old one was deleted for good)."""

from unittest.mock import patch

import pytest

from backend.services import docker_updates
from backend.services.container_mutator import recreate_container

INSPECT = {
    "Id": "abc123fullid000111222333444",
    "Name": "/web",
    "Config": {"Image": "busybox:1.36"},
    "HostConfig": {},
    "State": {"Running": True},
}


def _run(states, **kw):
    """recreate_container with the given live states after the start; returns the Docker calls."""
    seq = [(204, {}), (204, {}), (201, {"Id": "new_id_123456789"}), (204, {})] + [(200, {"State": s}) for s in states]
    calls = []

    def fake(method, path, **_):
        calls.append((method, path))
        return seq.pop(0) if seq else (204, {})

    with (
        patch("backend.services.container_mutator.fetch_container_raw_inspect", return_value=INSPECT),
        patch("backend.services.container_mutator._docker_request", side_effect=fake),
    ):
        try:
            return recreate_container(INSPECT["Id"], image="busybox:1.37", **kw), calls
        except RuntimeError as e:
            return e, calls


def test_a_version_that_stops_with_exit_code_0_goes_back():
    res, calls = _run([{"Running": False, "ExitCode": 0}], grace_period_seconds=0.2)
    assert isinstance(res, RuntimeError) and "stopped right after it started" in str(res)
    assert ("POST", "/containers/abc123fullid000111222333444/rename?name=web") in calls


def test_a_one_shot_container_may_end_with_exit_code_0(monkeypatch):
    monkeypatch.setitem(INSPECT, "State", {"Running": False})
    res, _ = _run([{"Running": False, "ExitCode": 0}], grace_period_seconds=0.2)
    assert res["status"] == "success"


def test_a_restarting_container_is_judged_by_its_restart_count():
    res, _ = _run([{"Running": False, "Restarting": True, "ExitCode": 0, "RestartCount": 1}], grace_period_seconds=0.2)
    assert isinstance(res, RuntimeError) and "restarted 1 times" in str(res)


def test_a_slow_health_check_is_fine_for_an_update_but_unhealthy_is_not():
    starting = {"Running": True, "ExitCode": 0, "Health": {"Status": "starting"}}
    res, _ = _run([starting] * 50, grace_period_seconds=0.15, starting_ok=True)
    assert res["status"] == "success"
    res, _ = _run([starting] * 50, grace_period_seconds=0.15)
    assert isinstance(res, RuntimeError) and "expected 'healthy'" in str(res)
    bad = {"Running": True, "ExitCode": 0, "Health": {"Status": "unhealthy", "FailingStreak": 3}}
    res, _ = _run([bad], grace_period_seconds=0.15, starting_ok=True)
    assert isinstance(res, RuntimeError) and "unhealthy" in str(res)


@pytest.mark.parametrize("running,grace", [(True, docker_updates.UPDATE_GRACE_SECS), (False, 0.0)])
def test_update_waits_only_for_an_app_that_was_running(monkeypatch, running, grace):
    seen = {}
    inspect = {**INSPECT, "State": {"Running": running}}
    monkeypatch.setattr("backend.services.compose_synthesizer.fetch_container_raw_inspect", lambda cid: inspect)
    monkeypatch.setattr(docker_updates, "pull_container_image", lambda img, timeout=0: True)
    monkeypatch.setattr(
        docker_updates, "recreate_container", lambda cid, **kw: seen.update(kw) or {"status": "success"}
    )
    docker_updates.update_single_container("web", keep_backup=True)
    assert seen["grace_period_seconds"] == grace and seen["keep_backup"] is True and seen["starting_ok"] is True


def test_going_back_counts_the_update_again(monkeypatch):
    entry = {"name": "web", "has_update": False, "status": "up_to_date"}
    other = {"name": "db", "has_update": True, "status": "update_available"}
    monkeypatch.setattr(
        docker_updates,
        "_update_cache",
        {"containers": {"web": entry, "id1": entry, "db": other}, "updates_available_count": 1},
    )
    docker_updates.mark_update_pending("web")
    assert entry["has_update"] is True and docker_updates._update_cache["updates_available_count"] == 2
