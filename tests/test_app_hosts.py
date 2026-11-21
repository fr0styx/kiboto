"""On a machine Kiboto runs on without a container, apps are reached by name through /etc/hosts."""

import pytest

from backend import runtime
from backend.services import app_hosts, docker_client

RUNNING = [
    {
        "Names": ["/kiboto-ai"],
        "State": "running",
        "NetworkSettings": {"Networks": {"kiboto-app-ai": {"IPAddress": "10.213.4.2"}}},
    },
    {"Names": ["/jellyfin"], "State": "running", "NetworkSettings": {"Networks": {"host": {"IPAddress": ""}}}},
    {
        "Names": ["/immich"],
        "State": "running",
        "NetworkSettings": {"Networks": {"b": {"IPAddress": "10.213.1.5"}, "a": {"IPAddress": "10.213.0.9"}}},
    },
    {"Names": ["/stopped"], "State": "exited", "NetworkSettings": {"Networks": {"bridge": {"IPAddress": ""}}}},
    {"Names": ["/no-address"], "State": "running", "NetworkSettings": {"Networks": {"none": {}}}},
    {
        "Names": ["/bad name\n1.2.3.4 evil"],
        "State": "running",
        "NetworkSettings": {"Networks": {"bridge": {"IPAddress": "10.212.0.7"}}},
    },
]


def test_names_and_addresses_come_from_dockers_list():
    assert app_hosts.addresses(RUNNING) == {
        "kiboto-ai": "10.213.4.2",
        "jellyfin": "127.0.0.1",  # on the host's own network: it is the machine itself
        "immich": "10.213.0.9",  # several networks: the first by name, so it does not flip between writes
    }


def test_only_kibotos_block_changes():
    mine = "127.0.0.1\tlocalhost\n192.168.1.20 printer   # mine\n"
    once = app_hosts.with_block(mine, {"kiboto-ai": "10.213.4.2"})
    assert once.startswith(mine.rstrip("\n")) and "10.213.4.2\tkiboto-ai" in once
    assert once.count(app_hosts.BEGIN) == 1 and once.endswith(app_hosts.END + "\n")
    twice = app_hosts.with_block(once, {"kiboto-ai": "10.213.4.9", "immich": "10.213.0.9"})
    assert twice.count(app_hosts.BEGIN) == 1 and "10.213.4.2" not in twice
    assert twice.index("immich") < twice.index("kiboto-ai")  # sorted: the same containers give the same file
    assert app_hosts.with_block(twice, {}) == mine  # no containers: the file as the person left it
    assert app_hosts.with_block(app_hosts.with_block(mine, {}), {}) == mine


@pytest.fixture
def managed(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    monkeypatch.setattr(docker_client, "request", lambda *a, **k: (200, RUNNING))
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1\tlocalhost\n")
    return hosts


def test_the_file_is_written_when_something_changed_and_only_then(managed):
    assert app_hosts.sync(str(managed)) is True
    text = managed.read_text()
    assert "127.0.0.1\tlocalhost" in text and "10.213.4.2\tkiboto-ai" in text and "evil" not in text
    assert app_hosts.sync(str(managed)) is False  # nothing came or went


def test_docker_being_down_keeps_the_known_names(managed, monkeypatch):
    app_hosts.sync(str(managed))
    before = managed.read_text()

    def down(*a, **k):
        raise docker_client.DockerUnavailable(0, "no socket")

    monkeypatch.setattr(docker_client, "request", down)
    assert app_hosts.sync(str(managed)) is False and managed.read_text() == before
    monkeypatch.setattr(docker_client, "request", lambda *a, **k: (500, None))
    assert app_hosts.sync(str(managed)) is False and managed.read_text() == before


def test_another_machines_hosts_file_is_never_written(managed, monkeypatch):
    monkeypatch.setattr(runtime, "managed_host", lambda: False)
    assert app_hosts.sync(str(managed)) is False
    assert managed.read_text() == "127.0.0.1\tlocalhost\n"


def test_a_file_that_cannot_be_written_is_said_not_raised(managed, tmp_path):
    blocked = tmp_path / "a-file"
    blocked.write_text("")  # no file can be made under a file
    assert app_hosts.sync(str(blocked / "hosts")) is False


def test_the_loop_keeps_going_after_a_failure(monkeypatch):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("docker hiccup")
        return False

    monkeypatch.setattr(app_hosts, "sync", flaky)
    monkeypatch.setattr(app_hosts.time, "sleep", lambda s: None)
    app_hosts.keep_in_step(rounds=3)
    assert len(calls) == 3


def test_native_an_app_still_gets_a_network_of_its_own(monkeypatch):
    from backend.services import app_networks

    asked = []

    def docker(method, path, body=None, **k):
        asked.append((method, path))
        if path.startswith("/containers/"):
            return 404, None  # Kiboto is no container here
        if method == "GET" and path.startswith("/networks/"):
            return 404, None
        return 201, {}

    monkeypatch.setattr(app_networks.docker_client, "request", docker)
    assert app_networks.private_network("frigate") is None  # in a container that cannot find itself: as before
    monkeypatch.setattr(runtime, "native", lambda: True)
    assert app_networks.private_network("frigate") == "kiboto-app-frigate"
    assert ("POST", "/networks/create") in asked
    assert not [a for a in asked if a[1].endswith("/connect")]  # nothing to join: the machine reaches it directly


def test_the_names_follow_the_containers_on_a_managed_host_only(monkeypatch):
    from backend import main

    started = []
    monkeypatch.setattr("backend.services.supervisor.supervise", lambda name, target, *a, **k: started.append(name))
    main._start_app_names()
    assert started == []
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    main._start_app_names()
    assert started == ["AppNames"]
