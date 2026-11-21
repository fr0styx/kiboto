"""Deleting unused Docker volumes needs a confirmation the server checks; the rest of the clean-up does not."""

import pytest


@pytest.fixture
def started(monkeypatch):
    from backend.services import docker_cleanup

    calls = []
    monkeypatch.setattr(
        docker_cleanup, "start_prune_job", lambda **kw: calls.append(kw) or ({"id": "j1", "state": "running"}, True)
    )
    done = {
        "success": True,
        "message": "ok",
        "space_reclaimed_bytes": 0,
        "space_reclaimed_human": "0 B",
        **{f"{k}_deleted": [] for k in ("containers", "images", "networks", "volumes")},
        **{f"{k}_deleted_count": 0 for k in ("containers", "images", "networks", "volumes", "build_caches")},
    }
    monkeypatch.setattr(docker_cleanup, "prune_docker_system", lambda **kw: calls.append(kw) or done)
    return calls


@pytest.mark.real_confirmations
@pytest.mark.parametrize("route", ["/api/docker/system/prune/jobs", "/api/docker/system/prune"])
def test_volumes_wait_for_a_confirmation(client, auth_headers, started, route):
    r = client.post(route, json={"prune_volumes": True}, headers=auth_headers)
    assert r.status_code == 428 and r.json()["action"] == "docker.prune.volumes"
    assert started == []
    token = client.post(
        "/api/confirmations", json={"action": "docker.prune.volumes", "target": ""}, headers=auth_headers
    ).json()["token"]
    r = client.post(route, json={"prune_volumes": True}, headers={**auth_headers, "X-Confirm-Token": token})
    assert r.status_code == 200 and started[-1]["prune_volumes"] is True


@pytest.mark.real_confirmations
def test_the_rest_of_the_clean_up_needs_none(client, auth_headers, started):
    r = client.post("/api/docker/system/prune/jobs", json={"prune_images": True}, headers=auth_headers)
    assert r.status_code == 200 and started[-1]["prune_volumes"] is False
