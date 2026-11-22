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


def test_natively_kiboto_looks_itself_up_nowhere(native_named_cafe, monkeypatch):
    from backend.api import system
    from backend.services import (
        app_networks,
        compose_synthesizer,
        docker_client,
        ip_block,
        iscsi_target,
        nas_name,
        tier_merge,
        tiering,
    )

    def asked(*a, **k):
        raise AssertionError(f"Docker asked about a container of Kiboto own: {a}")

    monkeypatch.setattr(docker_client, "request", asked)
    monkeypatch.setattr(compose_synthesizer, "fetch_container_raw_inspect", asked)
    for module in (nas_name, iscsi_target, tiering, tier_merge):
        monkeypatch.setattr(module, "_docker", asked)
    assert runtime.own_container_refs() == ()
    assert system._own_container_info() is None
    assert app_networks._me() is None
    assert nas_name._self() == iscsi_target._self() == tiering._self() == tier_merge._self() == {}
    ip_block._app_net["at"] = -1e9
    monkeypatch.setattr(ip_block, "APP_NETWORK_SECS", 0)
    assert ip_block._app_networks() == ()


def test_in_a_container_it_is_looked_up_by_id_then_name(monkeypatch):
    from backend.api import system
    from backend.services import compose_synthesizer

    monkeypatch.setattr(socket, "gethostname", lambda: CAFE[:12])
    refs = runtime.own_container_refs()
    assert refs[0] == CAFE[:12] and "kiboto" in refs
    seen = []
    monkeypatch.setattr(
        compose_synthesizer,
        "fetch_container_raw_inspect",
        lambda ref: seen.append(ref) or (ref == "kiboto" and {"Name": "/kiboto"}),
    )
    assert system._own_container_info() == {"Name": "/kiboto"} and seen[:2] == [CAFE[:12], "kiboto"]
