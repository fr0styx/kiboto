"""Where Kiboto runs, and where it keeps apps there.

Started as a process on a Debian machine, Kiboto asked Docker for "its own container" to learn where
apps keep their data, found none and fell back to Unraid's /mnt/user/appdata, a folder it then made on
the system disk."""

import os

import pytest

from backend import config, runtime
from backend.services import app_catalog, docker_stacks, immich_sso


@pytest.fixture
def no_marks(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "dockerenv"), str(tmp_path / "containerenv")))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(tmp_path / "etc" / "managed"))
    return tmp_path


def test_a_container_is_told_by_its_marks_or_by_the_setting(no_marks, monkeypatch):
    assert runtime.native() and not runtime.in_container()
    (no_marks / "containerenv").write_text("")
    assert runtime.in_container() and not runtime.native()
    (no_marks / "containerenv").unlink()
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": True})())
    assert runtime.in_container()


def test_a_managed_host_is_native_and_was_set_up_for_kiboto(no_marks):
    assert runtime.managed_host() is False  # a process on any machine: not that machine's interface
    (no_marks / "etc").mkdir()
    (no_marks / "etc" / "managed").write_text("")
    assert runtime.managed_host() is True
    (no_marks / "dockerenv").write_text("")  # the mark inside a container means nothing
    assert runtime.managed_host() is False


@pytest.fixture
def native_apps(no_marks, monkeypatch):
    monkeypatch.setattr(config, "POOL_PATH", str(no_marks / "storage"))
    monkeypatch.setattr(app_catalog, "_STORAGE_ROOT", {})

    def no_docker(*a, **k):
        raise AssertionError("a native Kiboto has no container of its own to ask about")

    monkeypatch.setattr(app_catalog, "_docker_request", no_docker)
    return str(no_marks / "storage" / "appdata")


def test_native_apps_live_in_the_main_storage_folder(native_apps):
    assert app_catalog.default_storage_root() == native_apps
    assert docker_stacks._stack_dir("wiki") == os.path.join(native_apps, "wiki")


def test_immich_falls_back_to_the_systems_apps_folder(native_apps, monkeypatch):
    from backend.services import container_mutator

    monkeypatch.setattr(container_mutator, "_docker_request", lambda *a, **k: (404, None))
    assert immich_sso.app_dir() == os.path.join(native_apps, "immich")


def test_the_routes_use_the_systems_apps_folder_when_none_is_given(client, auth_headers, native_apps, monkeypatch):
    seen = {}

    def fake_stream(app_id, **kw):
        seen["root"] = kw.get("storage_root")
        yield {"step": "error", "done": True, "message": "stopped here on purpose"}

    monkeypatch.setattr(app_catalog, "stream_deploy_catalog_app", fake_stream)
    r = client.post("/api/docker/catalog/it-tools/deploy", json={}, headers=auth_headers)
    assert r.status_code == 200 and seen["root"] == native_apps
    seen.clear()
    r = client.post("/api/docker/catalog/it-tools/deploy", json={"storage_root": "/srv/apps"}, headers=auth_headers)
    assert seen["root"] == "/srv/apps"
    assert client.get("/api/docker/catalog/defaults", headers=auth_headers).json()["storage_root"] == native_apps


def test_the_storage_page_and_the_about_box_ask_the_same_question(client, auth_headers, no_marks, monkeypatch):
    from backend.api import storage

    assert storage._in_container() is False
    (no_marks / "dockerenv").write_text("")
    assert storage._in_container() is True
