"""On a machine set up for Kiboto, container names are looked up in the hosts file Kiboto keeps, not
asked of the resolver (each name that is not there cost seconds)."""

import socket

import pytest

from backend import runtime
from backend.services import ai_endpoints, app_hosts


@pytest.fixture
def managed(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    hosts = tmp_path / "hosts"
    hosts.write_text(
        app_hosts.with_block("127.0.0.1\tlocalhost\n", {"kiboto-ollama": "10.213.0.5", "web": "10.213.0.6"})
    )
    monkeypatch.setattr(app_hosts, "HOSTS", str(hosts))
    return hosts


def test_names_come_from_the_hosts_file(managed, monkeypatch):
    def slow(*a, **k):
        raise AssertionError("the resolver was asked")

    monkeypatch.setattr(socket, "getaddrinfo", slow)
    assert app_hosts.names(str(managed)) == {"kiboto-ollama", "web"}
    assert ai_endpoints._resolves("kiboto-ollama") is True
    assert ai_endpoints._resolves("ovms") is False


def test_a_hosts_file_without_the_block_or_unreadable(tmp_path):
    plain = tmp_path / "plain"
    plain.write_text("127.0.0.1 localhost\n")
    assert app_hosts.names(str(plain)) == set()
    assert app_hosts.names(str(tmp_path / "missing")) == set()


def test_elsewhere_the_resolver_answers(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda name, port: [] if name == "kiboto-ollama" else (_ for _ in ()).throw(OSError("no")),
    )
    assert ai_endpoints._resolves("kiboto-ollama") is True
    assert ai_endpoints._resolves("ovms") is False
