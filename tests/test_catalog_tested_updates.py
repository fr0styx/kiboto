"""Apps decision 7: a built-in catalog app updates to the version this Kiboto ships (its tested,
pinned digest), not to whatever its tag points to upstream today. Other images are unchanged."""

import pytest

from backend.services import docker_updates, image_ref

OLD = "sha256:" + "1" * 64
NEW = "sha256:" + "2" * 64
UPSTREAM = "sha256:" + "3" * 64


@pytest.fixture
def lock(monkeypatch):
    data = {"jellyfin/jellyfin:10.10": NEW, "postgres:16": NEW, "postgres:15": OLD}
    monkeypatch.setattr(image_ref, "_lock", lambda: data)
    return data


def _container(image, follows=True):
    labels = {"kiboto.image.follow-tag": "1"} if follows else {}
    return {"Names": ["/media"], "Id": "abc123456789", "Image": image, "Labels": labels}


def _no_registry(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a catalog app must not ask the registry")

    monkeypatch.setattr(docker_updates, "_docker_request", boom)
    monkeypatch.setattr(docker_updates, "get_container_update_policy", lambda name: "notify")


def test_tested_ref_by_tag_then_by_the_only_tag_of_the_repo(lock):
    assert image_ref.tested_ref(f"jellyfin/jellyfin:10.10@{OLD}") == f"jellyfin/jellyfin:10.10@{NEW}"
    assert image_ref.tested_ref(f"jellyfin/jellyfin:10.9@{OLD}") == f"jellyfin/jellyfin:10.10@{NEW}"  # catalog moved on
    assert image_ref.tested_ref(f"postgres:14@{OLD}") is None  # two tags shipped: which one is not ours to guess
    assert image_ref.tested_ref("someone/else:1") is None
    assert image_ref.tested_ref(f"jellyfin/jellyfin@{OLD}") is None  # pinned by its owner, without a tag
    assert image_ref.tested_ref("") is None


def test_an_older_pin_has_an_update_to_the_tested_version_without_asking_the_registry(lock, monkeypatch):
    _no_registry(monkeypatch)
    res = docker_updates._check_container_image_update(_container(f"jellyfin/jellyfin:10.10@{OLD}"))
    assert res["has_update"] is True and res["status"] == "update_available"
    assert res["tested_image"] == f"jellyfin/jellyfin:10.10@{NEW}"
    res = docker_updates._check_container_image_update(_container(f"jellyfin/jellyfin:10.10@{NEW}"))
    assert res["has_update"] is False and res["status"] == "up_to_date"


def test_the_update_pulls_the_tested_version(lock):
    assert docker_updates._update_target(f"postgres:16@{OLD}") == f"postgres:16@{NEW}"


def test_images_outside_the_catalog_still_follow_their_tag(lock, monkeypatch):
    monkeypatch.setattr(docker_updates, "get_container_update_policy", lambda name: "notify")
    monkeypatch.setattr(docker_updates, "get_registry_auth_header", lambda img: {})
    calls = []

    def fake(method, path, **kw):
        calls.append(path)
        if path.startswith("/distribution/"):
            return 200, {"Descriptor": {"digest": UPSTREAM}}
        return 200, {"RepoDigests": []}

    monkeypatch.setattr(docker_updates, "_docker_request", fake)
    res = docker_updates._check_container_image_update(_container(f"someone/app:2@{OLD}"))
    assert res["has_update"] is True and calls[0] == "/distribution/someone/app:2/json"
    assert docker_updates._update_target(f"someone/app:2@{OLD}") == "someone/app:2"
