"""A pinned catalog image is pulled by its digest.

The install cut "name:tag@sha256:<hash>" at its last colon and asked Docker for the image
"name:tag@sha256" with the tag "<hash>". Docker 29 puts that back together; Docker 26, which Debian 13
ships, answers "invalid reference format", so no catalog app could be installed there."""

import pytest

from backend.services import app_catalog

DIGEST = "sha256:" + "8b" * 32


class FakeDocker:
    """Stands in for the Docker socket: records the pull that is asked for and refuses it."""

    asked: list[str] = []

    def __init__(self, *a, **k):
        pass

    def request(self, method, path, *a, **k):
        FakeDocker.asked.append(f"{method} {path}")

    def getresponse(self):
        class Res:
            status = 500

            def read(self):
                return b'{"message":"stopped here on purpose"}'

        return Res()

    def close(self):
        pass


@pytest.mark.parametrize(
    "image, want",
    [
        (f"example/tools:latest@{DIGEST}", f"fromImage=example/tools&tag=sha256%3A{'8b' * 32}"),
        ("example/tools:1.4", "fromImage=example/tools&tag=1.4"),
        ("example/tools", "fromImage=example/tools&tag=latest"),
        (
            f"registry.example:5000/team/tools:2@{DIGEST}",
            f"fromImage=registry.example%3A5000/team/tools&tag=sha256%3A{'8b' * 32}",
        ),
    ],
)
def test_the_install_pulls_a_pinned_image_by_its_digest(monkeypatch, tmp_path, image, want):
    app = {"name": "Tools", "image": image, "default_port": 8086, "env": {}, "volumes": {}}
    sock = tmp_path / "docker.sock"
    sock.write_text("")
    FakeDocker.asked = []
    monkeypatch.setattr(app_catalog, "get_catalog_app", lambda _id: dict(app))
    monkeypatch.setattr(app_catalog, "_docker_request", lambda *a, **k: (404, None))
    monkeypatch.setattr(app_catalog, "docker_sock", lambda: str(sock))
    monkeypatch.setattr(app_catalog, "UnixHTTPConnection", FakeDocker)
    monkeypatch.setattr("backend.services.image_ref.pinned", lambda ref: ref)  # the test's own reference stays
    events = list(app_catalog.stream_deploy_catalog_app("tools", host_port=18086, storage_root=str(tmp_path / "apps")))
    assert FakeDocker.asked == [f"POST /images/create?{want}"]
    assert events[-1]["step"] == "error" and "stopped here on purpose" in events[-1]["message"]
