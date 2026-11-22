"""After settings came back from a pool copy, the apps whose files are on the pools start again."""

import os

import pytest

from backend import state
from backend.services import app_catalog, apps_back, compose_apply, docker_stacks


@pytest.fixture
def apps(tmp_path, monkeypatch):
    root = tmp_path / "appdata"
    for name, text in (
        ("it-tools", "services:\n  web:\n    image: x\n"),
        ("wiki", "services:\n  web:\n    image: y\n"),
        ("vpn", "services:\n  vpn:\n    image: z\n    network_mode: host\n"),
        ("broken", "services:\n  web:\n    image: q\n"),
    ):
        (root / name).mkdir(parents=True)
        (root / name / "docker-compose.yml").write_text(text)
    (root / "wiki" / ".env").write_text("PASSWORD=secret\n")
    (root / "notes").mkdir()  # a folder without a Compose file is not an app
    (root / ".kiboto").mkdir()
    (root / ".kiboto" / "compose.yaml").write_text("services: {}\n")
    monkeypatch.setattr(app_catalog, "default_storage_root", lambda: str(root))
    events = []
    monkeypatch.setattr(state, "add_event", lambda level, title, msg, details=None: events.append((level, title, msg)))
    return type("Apps", (), {"root": root, "events": events})()


def docker(running=(), answers=True):
    def request(method, path, body=None, headers=None):
        if not answers:
            raise OSError("no docker socket")
        return 200, [{"Labels": {"com.docker.compose.project": n}} for n in running] + [{"Labels": {}}]

    return request


def test_the_apps_without_a_container_are_found(apps):
    assert apps_back.waiting(str(apps.root), docker(running=["wiki"])) == ["broken", "it-tools", "vpn"]
    assert apps_back.waiting(str(apps.root / "missing"), docker()) == []
    with pytest.raises(RuntimeError):
        apps_back.waiting(str(apps.root), lambda *a, **k: (500, None))


def test_each_app_is_applied_from_its_own_file_and_env(apps, monkeypatch):
    seen = []

    def inputs(name, compose, env):
        seen.append((name, compose.splitlines()[1].strip(), env))
        if name == "vpn":
            raise compose_apply.ComposeError("The file asks for host-level access; confirm it first.")
        return {"built": name, "current": []}

    def apply_built(built, current, docker_, elevated_ok, **kw):
        assert elevated_ok is False  # nothing with host-level access is started without a yes
        return {"ok": built != "broken", "error": "image q could not be downloaded"}

    monkeypatch.setattr(docker_stacks, "_apply_inputs", inputs)
    monkeypatch.setattr(compose_apply, "apply_built", apply_built)
    done = apps_back.start_all(request=docker(), sleep=lambda s: None)
    assert done == {"broken": "image q could not be downloaded", "it-tools": "", "vpn": "needs_ok", "wiki": ""}
    assert ("wiki", "web:", "PASSWORD=secret\n") in seen and ("it-tools", "web:", None) in seen
    assert apps.events == [
        ("success", "Apps started again", "it-tools, wiki"),
        (
            "warning",
            "Apps waiting for your OK",
            "vpn ask for access to the machine itself, so they were not started. Start them under Apps.",
        ),
        ("warning", "An app did not start", "broken: image q could not be downloaded"),
    ]


def test_another_refusal_of_the_file_is_said_as_it_is(apps, monkeypatch):
    def inputs(name, compose, env):
        raise compose_apply.ComposeError("This stack holds Kiboto itself, which never replaces its own container.")

    monkeypatch.setattr(docker_stacks, "_apply_inputs", inputs)
    assert apps_back.start_one("it-tools", str(apps.root)).startswith("This stack holds Kiboto itself")


def test_docker_is_waited_for_and_given_up_on(apps):
    slept = []
    assert apps_back.start_all(request=docker(answers=False), sleep=slept.append) == {}
    assert sum(slept) >= apps_back.WAIT_FOR_DOCKER and apps.events == []


def test_nothing_to_start_says_nothing(apps):
    assert (
        apps_back.start_all(request=docker(running=["it-tools", "wiki", "vpn", "broken"]), sleep=lambda s: None) == {}
    )
    assert apps.events == []


def test_apps_start_only_at_the_start_after_a_restore(tmp_path, monkeypatch):
    from backend.services import pool_copy

    monkeypatch.setattr(pool_copy, "_restored_at_start", [False])
    assert pool_copy.drop_index_after_restore(str(tmp_path)) is False
    assert pool_copy.restored_at_this_start() is False
    (tmp_path / pool_copy.ADOPT_FLAG).write_text("x")
    assert pool_copy.drop_index_after_restore(str(tmp_path)) is True
    assert pool_copy.restored_at_this_start() is True
    assert os.path.exists(tmp_path / pool_copy.ADOPT_FLAG)  # the pool record still reads it after
