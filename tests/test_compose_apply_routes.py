"""Apps decision 4b: the stack editor's preview and apply routes, and going back on failure."""

import threading

import pytest

from backend.services import docker_stacks as ds

FILE = "services:\n  web:\n    image: nginx:1.27\n    ports: ['8080:80']\n"


@pytest.fixture
def stack(monkeypatch, tmp_path):
    state = {
        "details": {
            "location_type": "host_fs",
            "working_dir": str(tmp_path),
            "compose_yaml": "services: {web: {image: nginx:1.26}}",
            "env_content": "",
            "has_real_file": True,
            "containers": [{"id": "abc", "name": "shop-web-1"}],
        },
        "saved": [],
    }
    monkeypatch.setattr(ds, "get_stack_details", lambda name: state["details"])
    monkeypatch.setattr(ds, "is_kiboto_itself", lambda cid, name="": False)
    monkeypatch.setattr(
        "backend.services.container_mutator.docker_request",
        lambda m, p, body=None, headers=None: (
            200,
            {
                "Name": "/shop-web-1",
                "State": {"Running": True},
                "Config": {"Image": "nginx:1.26", "Labels": {"com.docker.compose.service": "web"}},
                "HostConfig": {},
            },
        ),
    )
    monkeypatch.setattr(ds, "save_stack_config", lambda name, c, e=None: state["saved"].append(c) or {"success": True})
    return state


def test_preview_says_what_changes(stack):
    p = ds.preview_stack_apply("shop", FILE, "")
    assert p["steps"] == [
        {
            "service": "web",
            "action": "replace",
            "image": "nginx:1.27",
            "why": ["image nginx:1.26 → nginx:1.27", "ports"],
        }
    ]
    assert p["elevated"] == []


def test_refusals(stack):
    from backend.services.compose_apply import ComposeError

    stack["details"]["location_type"] = "dockhand"
    with pytest.raises(ComposeError, match="Dockhand"):
        ds.preview_stack_apply("shop", FILE)
    stack["details"]["location_type"] = "host_fs"
    ds.is_kiboto_itself = lambda cid, name="": True  # monkeypatch fixture restores it
    with pytest.raises(ComposeError, match="Kiboto itself"):
        ds.preview_stack_apply("shop", FILE)


def test_apply_runs_as_a_job_and_the_old_file_comes_back_on_failure(stack, monkeypatch):
    from backend.services import compose_apply
    from backend.services.jobs import job_manager

    monkeypatch.setattr(ds, "is_kiboto_itself", lambda cid, name="": False)
    finished = threading.Event()
    real_finish = job_manager.finish
    seen = {}

    def finish(jid, status="done", error=None, **kw):
        seen.update(status=status, error=error, **kw)
        real_finish(jid, status, error, **kw)
        finished.set()

    monkeypatch.setattr(job_manager, "finish", finish)
    monkeypatch.setattr(
        compose_apply,
        "apply_built",
        lambda *a, **k: {"ok": False, "error": "web stopped. Everything is back as it was."},
    )
    res = ds.start_stack_apply("shop", FILE, "", False, owner="admin")
    assert res["status"] == "started" and res["job"].startswith("job:")
    assert finished.wait(5) and seen["status"] == "error" and "Everything is back" in seen["error"]
    assert [s.strip() for s in stack["saved"]] == [
        FILE.strip(),
        "services: {web: {image: nginx:1.26}}",
    ]  # saved, then the old file back
    finished.clear()
    monkeypatch.setattr(compose_apply, "apply_built", lambda *a, **k: {"ok": True, "error": ""})
    ds.start_stack_apply("shop", FILE, "", False)
    assert finished.wait(5) and seen["status"] == "done"
    finished.clear()

    def boom(*a, **k):
        raise OSError("socket gone")

    monkeypatch.setattr(compose_apply, "apply_built", boom)
    ds.start_stack_apply("shop", FILE, "", False)
    assert finished.wait(5) and seen["status"] == "error" and "socket gone" in seen["error"]


def test_apply_refuses_host_access_without_an_ok_and_a_failed_save(stack, monkeypatch):
    from backend.services.compose_apply import ComposeError

    monkeypatch.setattr(ds, "_elevated", lambda body: ["privileged"])
    with pytest.raises(ComposeError, match="host-level access"):
        ds.start_stack_apply("shop", FILE, "", False)
    monkeypatch.setattr(ds, "_elevated", lambda body: [])
    monkeypatch.setattr(ds, "save_stack_config", lambda *a: {"success": False, "error": "disk full"})
    with pytest.raises(ComposeError, match="disk full"):
        ds.start_stack_apply("shop", FILE, "", False)


def test_routes(client, auth_headers, monkeypatch):
    from backend.services.compose_apply import ComposeError

    monkeypatch.setattr(ds, "preview_stack_apply", lambda n, c, e=None: {"steps": [], "elevated": []})
    monkeypatch.setattr(ds, "start_stack_apply", lambda *a: {"status": "started", "job": "job:1", "steps": []})
    body = {"compose_yaml": FILE, "env_content": ""}
    assert client.post("/api/docker/stacks/shop/preview", json=body, headers=auth_headers).json() == {
        "steps": [],
        "elevated": [],
    }
    assert client.post("/api/docker/stacks/shop/apply", json=body, headers=auth_headers).json()["job"] == "job:1"
    assert client.post("/api/docker/stacks/bad name!/preview", json=body, headers=auth_headers).status_code in (
        400,
        404,
    )

    def bad(*a):
        raise ComposeError("nope")

    monkeypatch.setattr(ds, "preview_stack_apply", bad)
    assert client.post("/api/docker/stacks/shop/preview", json=body, headers=auth_headers).status_code == 400
    assert client.post("/api/docker/stacks/shop/apply", json=body, headers=auth_headers).status_code == 400


@pytest.mark.real_confirmations
def test_host_access_needs_a_confirmation(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        ds,
        "preview_stack_apply",
        lambda n, c, e=None: {"steps": [], "elevated": [{"service": "web", "reasons": ["privileged"]}]},
    )
    started = []
    monkeypatch.setattr(
        ds, "start_stack_apply", lambda *a: started.append(a) or {"status": "started", "job": "job:2", "steps": []}
    )
    body = {"compose_yaml": FILE, "env_content": ""}
    r = client.post("/api/docker/stacks/shop/apply", json=body, headers=auth_headers)
    assert r.status_code == 428 and r.json()["action"] == "docker.stack.apply.elevated" and not started
    tok = client.post(
        "/api/confirmations", json={"action": "docker.stack.apply.elevated", "target": "shop"}, headers=auth_headers
    ).json()["token"]
    r = client.post("/api/docker/stacks/shop/apply", json=body, headers={**auth_headers, "X-Confirm-Token": tok})
    assert r.status_code == 200 and started[0][3] is True
