"""Natively the host name is the NAS's name: no container passes for Kiboto itself because of it."""

import socket

import pytest

from backend import runtime
from backend.hardware import docker_stats
from backend.services import docker_cleanup

CAFE = "cafe0123456789abcdef0123456789abcdef0123456789abcdef0123456789ab"


@pytest.fixture
def native_named_cafe(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    monkeypatch.setattr(socket, "gethostname", lambda: "cafe")


def test_a_nas_named_like_a_container_id_does_not_claim_containers(native_named_cafe):
    assert runtime.own_container_hostname() == ""
    assert docker_stats.is_kiboto_itself(CAFE, "photos") is False
    assert docker_cleanup.is_self_container(CAFE, "photos") is False


def test_in_a_container_the_host_name_is_still_its_id(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: CAFE[:12])
    assert runtime.own_container_hostname() == CAFE[:12]  # tests run as in a container (conftest)
    assert docker_stats.is_kiboto_itself(CAFE, "") is True and docker_cleanup.is_self_container(CAFE, "") is True
