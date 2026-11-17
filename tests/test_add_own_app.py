"""Apps decision 3 with 4b: "Add your own app" is refused when its name is taken, then applied safely."""

import pytest

from backend.services import docker_stacks as ds

FILE = "services:\n  web:\n    image: nginx:1.27\n"


@pytest.fixture
def stacks(monkeypatch):
    monkeypatch.setattr(ds, "list_all_stacks", lambda: [{"name": "immich"}])
    monkeypatch.setattr(ds.os.path, "exists", lambda p: p == "/mnt/user/appdata/oldapp/compose.yaml")


@pytest.mark.parametrize(
    "name,problem",
    [
        ("web", None),
        ("my-app_2", None),
        ("My App", "Use small letters"),
        ("-x", "Use small letters"),
        ("../x", "Use small letters"),
        ("immich", "exists already"),
        ("oldapp", "already holds an app file"),
    ],
)
def test_the_name_must_be_free(stacks, name, problem):
    got = ds.new_stack_problem(name)
    assert (got is None) if problem is None else (problem in got)


def test_the_create_route(client, auth_headers, stacks, monkeypatch):
    body = {"compose_yaml": FILE, "env_content": ""}
    r = client.post("/api/docker/stacks/immich/create", json=body, headers=auth_headers)
    assert r.status_code == 409 and "exists already" in r.text
    answer = r.json()
    assert answer["error"] == "name_not_free" and answer["text"]["msg_key"] == "srv.own_app_name_taken"
    assert answer["text"]["params"] == {"name": "immich"}
    monkeypatch.setattr(ds, "preview_stack_apply", lambda n, c, e=None: {"steps": [], "elevated": []})
    monkeypatch.setattr(ds, "start_stack_apply", lambda *a: {"status": "started", "job": "job:7", "steps": []})
    r = client.post("/api/docker/stacks/web/create", json=body, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["job"] == "job:7"
