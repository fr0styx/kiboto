"""The in-app updater installs only this project's images."""

import pytest

from backend import legacy_names
from backend.api import system


@pytest.mark.parametrize(
    "ref,ok",
    [
        (f"ghcr.io/{legacy_names.OLD_IMAGE_REPO}:latest", True),
        (f"ghcr.io/{legacy_names.OLD_IMAGE_REPO}:1.9.2", True),
        (f"ghcr.io/{legacy_names.OLD_IMAGE_REPO}@sha256:" + "a" * 64, True),
        (f"ghcr.io/{legacy_names.OLD_IMAGE_REPO}-evil:latest", False),
        ("ghcr.io/attacker/kiboto:latest", False),
        ("docker.io/library/alpine:latest", False),
        (f"ghcr.io/{legacy_names.OLD_IMAGE_REPO}:latest;rm -rf /", False),
    ],
)
def test_official_image_refs(ref, ok):
    assert system._is_official_image_ref(ref) is ok


def test_apply_refuses_foreign_image_and_unverified_pull(client, auth_headers, monkeypatch):
    res = client.post(
        "/api/system/updates/apply",
        json={"channel": "stable", "target_image": "docker.io/attacker/backdoor:latest"},
        headers=auth_headers,
    )
    assert res.status_code == 400

    monkeypatch.setattr("backend.services.container_mutator.pull_container_image", lambda *a, **k: None)
    monkeypatch.setattr(system, "_local_repo_digests", lambda ref: [])
    spawned = []
    monkeypatch.setattr("backend.services.self_updater.spawn_self_updater", lambda *a, **k: spawned.append(a) or True)
    res = client.post("/api/system/updates/apply", json={"channel": "stable"}, headers=auth_headers)
    assert res.status_code == 502 and not spawned
