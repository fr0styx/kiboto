"""Run natively, apps reach Kiboto at their network's gateway, and the AI pack gets a network of its own."""

import pytest

from backend import runtime
from backend.services import ai_pack, app_after_start, app_networks, docker_client


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())


def test_an_app_reaches_kiboto_at_its_networks_gateway(native, monkeypatch):
    info = {
        "NetworkSettings": {"Networks": {"kiboto-app-nextcloud": {"Gateway": "10.213.3.1", "IPAddress": "10.213.3.2"}}}
    }
    monkeypatch.setattr(docker_client, "request", lambda method, path, *a, **k: (200, info))
    assert app_after_start.own_name("nextcloud") == "10.213.3.1"
    ctx = app_after_start.context("nas.local", 8080, "nextcloud")
    assert ctx["kiboto"] == "10.213.3.1"
    assert app_after_start.fill("http://{{kiboto}}:8084/", ctx, {}) == "http://10.213.3.1:8084/"


def test_without_a_gateway_the_name_is_kept(native, monkeypatch):
    monkeypatch.setattr(docker_client, "request", lambda method, path, *a, **k: (404, {}))
    assert app_after_start.own_name("gone") == "kiboto"

    def down(*a, **k):
        raise docker_client.DockerUnavailable(0, "no socket")

    monkeypatch.setattr(docker_client, "request", down)
    assert app_after_start.own_name("x") == "kiboto"


def test_the_ai_pack_gets_a_network_of_its_own(native, monkeypatch):
    asked = []
    monkeypatch.setattr(app_networks, "private_network", lambda app_id: asked.append(app_id) or "kiboto-app-kiboto-ai")
    monkeypatch.setattr(ai_pack, "pack_name", lambda: "kiboto-ai")
    monkeypatch.setattr(ai_pack, "_docker", lambda *a, **k: pytest.fail("no container of Kiboto's own is asked about"))
    assert ai_pack.own_network() == "kiboto-app-kiboto-ai" and asked == ["kiboto-ai"]


def test_the_kiboto_placeholder_is_filled():
    assert app_after_start.fill("http://{{kiboto}}:8084/", {"kiboto": "kiboto"}, {}) == "http://kiboto:8084/"
