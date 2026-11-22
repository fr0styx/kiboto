"""On a machine set up for Kiboto apps keep their data on the first pool, not on the system disk."""

import os

import pytest

from backend import config, runtime
from backend.hardware.pal import pool_registry
from backend.services import app_catalog, apps_place, docker_stacks


@pytest.fixture
def box(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    monkeypatch.setattr(config, "POOL_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(apps_place, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(app_catalog, "_STORAGE_ROOT", {})
    monkeypatch.setattr(app_catalog, "_docker_request", lambda *a, **k: pytest.fail("no container to ask"))
    rows = []
    monkeypatch.setattr(pool_registry, "load", lambda: rows)
    mounted = set()
    monkeypatch.setattr(os.path, "ismount", lambda p: p in mounted)
    return type("Box", (), {"rows": rows, "mounted": mounted, "root": tmp_path})()


def pool(box, name, ejected=False, mounted=True):
    mp = str(box.root / "storage" / name)
    box.rows.append({"name": name, "mountpoint": mp, "ejected": ejected})
    if mounted:
        box.mounted.add(mp)
    return mp


def test_without_a_pool_apps_fall_back_to_the_system_disk_and_ask_again_later(box):
    assert app_catalog.default_storage_root() == str(box.root / "storage" / "appdata")
    assert apps_place.recorded() == ""
    tank = pool(box, "tank")
    assert app_catalog.default_storage_root() == os.path.join(tank, "appdata")  # not stuck on the fallback
    assert docker_stacks._stack_dir("wiki") == os.path.join(tank, "appdata", "wiki")


def test_the_first_pool_is_chosen_once_and_stays(box):
    pool(box, "out", ejected=True)
    pool(box, "away", mounted=False)
    tank = pool(box, "tank")
    pool(box, "media")
    assert apps_place.root() == (os.path.join(tank, "appdata"), True)
    box.rows.insert(0, {"name": "older", "mountpoint": pool(box, "older"), "ejected": False})
    box.mounted.discard(tank)  # the pool is away: apps do not move to another one or to the system disk
    assert apps_place.root() == (os.path.join(tank, "appdata"), True)
    assert app_catalog.default_storage_root() == os.path.join(tank, "appdata")


def test_the_record_comes_back_with_the_settings(box):
    os.makedirs(box.root / "data" / "storage")
    (box.root / "data" / "storage" / "apps_place.json").write_text('{"root": "/mnt/storage/tank/appdata"}')
    assert apps_place.root() == ("/mnt/storage/tank/appdata", True)
    (box.root / "data" / "storage" / "apps_place.json").write_text('{"root": "relative/path"}')
    assert apps_place.recorded() == ""


def test_a_guest_and_a_plain_native_install_are_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(app_catalog, "_STORAGE_ROOT", {})
    monkeypatch.setattr(config, "POOL_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(tmp_path / "no-mark"))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    monkeypatch.setattr(apps_place, "root", lambda: pytest.fail("only a managed host"))
    assert app_catalog.default_storage_root() == str(tmp_path / "storage" / "appdata")
