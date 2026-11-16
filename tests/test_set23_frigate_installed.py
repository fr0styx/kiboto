"""SET-23: the Cameras card shows only when Frigate runs here; the API says so."""

from backend.services import docker_client, frigate_events


def test_installed_when_a_container_runs_frigates_image(monkeypatch):
    seen = []

    def req(method, path, *a, **k):
        seen.append((method, path))
        return 200, [{"Image": "nginx:1"}, {"Image": "ghcr.io/blakeblackshear/frigate:stable"}]

    monkeypatch.setattr(docker_client, "request", req)
    assert frigate_events.installed() is True
    assert seen == [("GET", "/containers/json?all=1")]


def test_not_installed_without_it_or_without_docker(monkeypatch):
    monkeypatch.setattr(docker_client, "request", lambda *a, **k: (200, [{"Image": "nginx:1"}]))
    assert frigate_events.installed() is False
    monkeypatch.setattr(docker_client, "request", lambda *a, **k: (500, {"message": "down"}))
    assert frigate_events.installed() is False

    for err in (OSError("no socket"), docker_client.DockerUnavailable(503, "no socket", "/containers/json")):

        def boom(*a, e=err, **k):
            raise e

        monkeypatch.setattr(docker_client, "request", boom)
        assert frigate_events.installed() is False


def test_the_settings_say_whether_frigate_is_there(monkeypatch):
    from backend.api import notifications

    monkeypatch.setattr(frigate_events, "installed", lambda: True)
    out = notifications.get_frigate_events()
    assert out["installed"] is True and "choices" in out and "enabled" in out
