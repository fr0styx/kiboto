"""Apps decision 2: a whole app of several containers is backed up, restored, updated and removed as one."""

import json
import tarfile
import threading

import pytest

from backend.services import app_backup, whole_app
from backend.services import docker_stacks as ds


@pytest.fixture
def app(monkeypatch, tmp_path):
    shared = tmp_path / "appdata" / "shop"
    db = tmp_path / "appdata" / "shop-db"
    shared.mkdir(parents=True)
    db.mkdir(parents=True)
    (shared / "site.conf").write_text("web")
    (db / "data.sql").write_text("db")
    parts = {
        "a1": {
            "Id": "a1",
            "Name": "/shop-web-1",
            "State": {"Running": True},
            "Config": {"Image": "nginx:1.27", "Labels": {"com.docker.compose.service": "web"}},
            "Mounts": [
                {"Type": "bind", "Source": str(shared), "Destination": "/etc/nginx", "RW": True},
                {"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock"},
            ],
        },
        "b2": {
            "Id": "b2",
            "Name": "/shop-db-1",
            "State": {"Running": False},
            "Config": {"Image": "postgres:17", "Labels": {"com.docker.compose.service": "db"}},
            "Mounts": [
                {"Type": "bind", "Source": str(db), "Destination": "/var/lib/postgresql", "RW": True},
                {"Type": "bind", "Source": str(shared), "Destination": "/shared", "RW": False},
            ],
        },
    }
    state = {
        "details": {
            "working_dir": str(tmp_path / "stack"),
            "compose_yaml": "services:\n  db: {image: postgres:17}\n  web: {image: nginx:1.27, depends_on: [db]}\n",
            "has_real_file": True,
            "containers": [
                {"id": "a1", "name": "shop-web-1", "service": "web"},
                {"id": "b2", "name": "shop-db-1", "service": "db"},
            ],
        },
        "calls": [],
        "gone": set(),
        "parts": parts,
        "shared": shared,
        "db": db,
    }

    def docker(method, path, **kwargs):
        state["calls"].append((method, path.split("?")[0]))
        if method == "GET":
            cid = path.split("/")[2]
            for p in parts.values():
                if cid in (p["Id"], p["Name"].lstrip("/")) and cid not in state["gone"]:
                    return 200, p
            return 404, {}
        return 204, {}

    monkeypatch.setattr(ds, "get_stack_details", lambda name: state["details"])
    monkeypatch.setattr(ds, "is_kiboto_itself", lambda cid, name="": False)
    monkeypatch.setattr(app_backup, "_docker_request", docker)
    monkeypatch.setattr(app_backup, "get_app_backup_base_dir", lambda: str(tmp_path / "backups"))
    monkeypatch.setattr(app_backup, "APP_BACKUPS_REGISTRY_FILE", str(tmp_path / "reg.json"))
    monkeypatch.setattr(app_backup, "_mark_paused", lambda kind, ident: True)
    monkeypatch.setattr(app_backup, "_unpause_container", lambda cid: state["calls"].append(("UNPAUSE", cid)))
    monkeypatch.setattr("backend.config.DATA_DIR", str(tmp_path / "data"))
    return state


def test_one_archive_holds_the_whole_app(app):
    rec = app_backup.create_stack_backup("shop")
    assert rec["app_name"] == "shop" and sorted(rec["containers"]) == ["shop-db-1", "shop-web-1"]
    assert rec["mounts_count"] == 2  # the shared folder once, the socket never
    with tarfile.open(rec["filepath"]) as tar:
        manifest = json.loads(tar.extractfile("manifest.json").read())
        names = tar.getnames()
        compose = tar.extractfile("docker-compose.yml").read().decode()
    assert manifest["stack"] == "shop" and manifest["working_dir"] == app["details"]["working_dir"]
    assert compose == app["details"]["compose_yaml"]  # the app's own file, not a rebuilt one
    assert any(n.endswith("site.conf") for n in names) and any(n.endswith("data.sql") for n in names)
    # only the running part was paused, and it was resumed
    assert ("POST", "/containers/a1/pause") in app["calls"] and ("POST", "/containers/b2/pause") not in app["calls"]
    assert ("UNPAUSE", "a1") in app["calls"]


def test_an_app_without_its_own_file_gets_one_rebuilt(app):
    app["details"]["has_real_file"] = False
    rec = app_backup.create_stack_backup("shop")
    with tarfile.open(rec["filepath"]) as tar:
        compose = tar.extractfile("docker-compose.yml").read().decode()
    assert "services:" in compose and "nginx:1.27" in compose and "postgres:17" in compose


def test_refusals(app, monkeypatch):
    monkeypatch.setattr(ds, "is_kiboto_itself", lambda cid, name="": cid == "a1")
    with pytest.raises(ValueError, match="Kiboto itself"):
        app_backup.create_stack_backup("shop")
    app["details"]["containers"] = []
    with pytest.raises(ValueError, match="No app named"):
        ds.app_details("shop")


def test_restore_holds_every_part_and_brings_a_removed_app_back(app, monkeypatch):
    rec = app_backup.create_stack_backup("shop")
    (app["db"] / "data.sql").write_text("broken")
    app["calls"].clear()
    res = app_backup.restore_app_backup(rec["id"])
    assert (app["db"] / "data.sql").read_text() == "db"
    assert res["outcome"] == "running_again"  # web ran and runs again, db stays stopped
    assert ("POST", "/containers/shop-web-1/stop") in app["calls"]
    assert ("POST", "/containers/shop-web-1/start") in app["calls"]
    assert ("POST", "/containers/shop-db-1/start") not in app["calls"]

    app["gone"].add("shop-db-1")
    assert app_backup.restore_app_backup(rec["id"])["outcome"] == "parts_missing"

    app["gone"].add("shop-web-1")
    seen = {}
    monkeypatch.setattr(
        app_backup, "_bring_back", lambda name, compose, base: seen.update(n=name, b=base) or ("brought_back", "")
    )
    res = app_backup.restore_app_backup(rec["id"])
    assert res["outcome"] == "brought_back" and seen == {"n": "shop", "b": app["details"]["working_dir"]}


def test_combined_outcomes():
    c = app_backup._combined
    assert c([]) == "files_only" and c(["files_only", "files_only"]) == "files_only"
    assert c(["files_only", "running_again"]) == "parts_missing"
    assert c(["running_again", "start_failed"]) == "start_failed"
    assert c(["stopped_kept", "running_again"]) == "running_again"
    assert c(["stopped_kept"]) == "stopped_kept"


def test_remove_keeps_a_backup_first_and_removes_the_last_started_first(app, monkeypatch):
    removed = []
    monkeypatch.setattr(
        "backend.services.docker_cleanup.destroy_container",
        lambda cid, force=False, archive_data=True: removed.append((cid, force, archive_data)),
    )
    res = whole_app.remove_app("shop")
    # db starts before web (depends_on), so web goes first
    assert removed == [("a1", True, False), ("b2", True, False)]
    assert res["success"] and res["backup"]["filename"].startswith("shop_uninstall_")
    assert len(app_backup.list_app_backups("shop")) == 1

    removed.clear()
    whole_app.remove_app("shop", keep_backup=False)
    assert len(app_backup.list_app_backups("shop")) == 1 and len(removed) == 2

    def fails(cid, force=False, archive_data=True):
        if cid == "a1":
            raise ValueError("busy")
        removed.append(cid)

    monkeypatch.setattr("backend.services.docker_cleanup.destroy_container", fails)
    res = whole_app.remove_app("shop", keep_backup=False)
    assert not res["success"] and res["failed"] == [{"name": "shop-web-1", "error": "busy"}]


def test_a_failed_backup_removes_nothing(app, monkeypatch):
    removed = []
    monkeypatch.setattr("backend.services.docker_cleanup.destroy_container", lambda *a, **k: removed.append(a))

    def full(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(app_backup, "create_stack_backup", full)
    with pytest.raises(OSError):
        whole_app.remove_app("shop")
    assert removed == []


def test_update_runs_part_by_part_as_a_job(app, monkeypatch):
    from backend.services.jobs import job_manager

    monkeypatch.setattr(
        "backend.services.docker_updates.check_all_container_updates",
        lambda force=False: {"containers": {"shop-web-1": {"has_update": True}, "shop-db-1": {"has_update": True}}},
    )
    updated = []
    monkeypatch.setattr(
        "backend.services.docker_updates.update_single_container",
        lambda n, keep_backup=False: (
            updated.append(n) or {"target_name": n, "old_id": f"old-{n}", "new_id": f"new-{n}"}
        ),
    )
    calls = []
    monkeypatch.setattr(
        "backend.services.container_mutator.docker_request",
        lambda method, path, **kw: calls.append((method, path)) or (204, {}),
    )
    finished = threading.Event()
    seen = {}
    real = job_manager.finish

    def finish(jid, status="done", error=None, **kw):
        seen.update(status=status, error=error, **kw)
        real(jid, status, error, **kw)
        finished.set()

    monkeypatch.setattr(job_manager, "finish", finish)
    res = whole_app.start_app_update("shop", owner="admin")
    assert res["status"] == "started" and res["parts"] == ["shop-db-1", "shop-web-1"]
    assert finished.wait(5) and seen["status"] == "done" and updated == ["shop-db-1", "shop-web-1"]
    # the old containers kept for going back are removed once the whole app runs
    assert calls == [
        ("DELETE", "/containers/old-shop-db-1?v=false&force=true"),
        ("DELETE", "/containers/old-shop-web-1?v=false&force=true"),
    ]

    finished.clear()
    calls.clear()

    def second_fails(name, keep_backup=False):
        if name == "shop-web-1":
            raise RuntimeError("pull failed")
        updated.append(name)
        return {"target_name": name, "old_id": f"old-{name}", "new_id": f"new-{name}"}

    monkeypatch.setattr("backend.services.docker_updates.update_single_container", second_fails)
    whole_app.start_app_update("shop")
    assert finished.wait(5) and seen["status"] == "error"
    assert (
        "shop-web-1 could not be updated: pull failed. The parts" in seen["error"]
        and "went back to their old versions" in seen["error"]
    )
    # the Jobs centre words it in the reader's language
    assert seen["error_id"] == "jobs.e.app_update_back"
    assert seen["error_params"] == {"app": "shop", "name": "shop-web-1", "reason": "pull failed"}
    # the part already updated is put back on its old container
    assert calls == [
        ("DELETE", "/containers/new-shop-db-1?v=false&force=true"),
        ("POST", "/containers/old-shop-db-1/rename?name=shop-db-1"),
        ("POST", "/containers/old-shop-db-1/start"),
    ]

    finished.clear()
    monkeypatch.setattr(
        "backend.services.container_mutator.docker_request",
        lambda method, path, **kw: (404, {}) if "rename" in path else (204, {}),
    )
    whole_app.start_app_update("shop")
    assert finished.wait(5) and "Could not put back: shop-db-1." in seen["error"]
    assert seen["error_id"] == "jobs.e.app_update_stuck" and seen["error_params"]["stuck"] == "shop-db-1"

    def first_fails(name, keep_backup=False):
        raise RuntimeError("pull failed")

    finished.clear()
    monkeypatch.setattr("backend.services.docker_updates.update_single_container", first_fails)
    whole_app.start_app_update("shop")
    assert finished.wait(5) and seen["error_id"] == "jobs.e.app_update_failed"

    monkeypatch.setattr("backend.services.docker_updates.check_all_container_updates", lambda force=False: {})
    assert whole_app.start_app_update("shop") == {"status": "up_to_date", "parts": []}


def test_routes(client, auth_headers, monkeypatch):
    monkeypatch.setattr(app_backup, "create_stack_backup", lambda n: {"id": "abk_1", "filename": "shop.tar.gz"})
    monkeypatch.setattr(
        whole_app, "start_app_update", lambda n, o=None: {"status": "started", "job": "job:9", "parts": []}
    )
    monkeypatch.setattr(whole_app, "remove_app", lambda n, k=True: {"success": True, "kept": k})
    assert client.post("/api/docker/stacks/shop/backup", headers=auth_headers).json()["backup"]["id"] == "abk_1"
    assert client.post("/api/docker/stacks/shop/update", headers=auth_headers).json()["job"] == "job:9"
    assert client.delete("/api/docker/stacks/shop", headers=auth_headers).json() == {"success": True, "kept": True}
    assert client.delete("/api/docker/stacks/shop?keep_backup=false", headers=auth_headers).json()["kept"] is False
    assert client.post("/api/docker/stacks/bad name!/backup", headers=auth_headers).status_code in (400, 404)

    def nope(*a, **k):
        raise ValueError("No app named 'shop'.")

    def full(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(app_backup, "create_stack_backup", nope)
    monkeypatch.setattr(whole_app, "start_app_update", nope)
    assert client.post("/api/docker/stacks/shop/backup", headers=auth_headers).status_code == 400
    assert client.post("/api/docker/stacks/shop/update", headers=auth_headers).status_code == 400
    monkeypatch.setattr(whole_app, "remove_app", nope)
    assert client.delete("/api/docker/stacks/shop", headers=auth_headers).status_code == 400
    monkeypatch.setattr(whole_app, "remove_app", full)
    assert client.delete("/api/docker/stacks/shop", headers=auth_headers).status_code == 409


@pytest.mark.real_confirmations
def test_remove_needs_a_confirmation(client, auth_headers, monkeypatch):
    removed = []
    monkeypatch.setattr(whole_app, "remove_app", lambda n, k=True: removed.append(n) or {"success": True})
    r = client.delete("/api/docker/stacks/shop", headers=auth_headers)
    assert r.status_code == 428 and r.json()["action"] == "docker.stack.remove" and not removed
