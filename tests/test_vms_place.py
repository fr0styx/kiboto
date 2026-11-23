"""On a machine set up for Kiboto, virtual machines and installer images go on the first pool."""

import os

import pytest

from backend import config, places, runtime
from backend.hardware.pal import pool_registry
from backend.services import pool_places, vm_host, vm_store


@pytest.fixture
def box(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", str(data))
    tank = tmp_path / "storage" / "tank"
    tank.mkdir(parents=True)
    rows = []
    monkeypatch.setattr(pool_registry, "load", lambda: [dict(r) for r in rows])
    real = os.path.ismount
    monkeypatch.setattr(os.path, "ismount", lambda p: str(p) == str(tank) or real(p))
    return type("Box", (), {"data": str(data), "tank": str(tank), "rows": rows})


def test_machines_go_on_the_first_pool(box, monkeypatch):
    assert pool_places.vms_root(box.data) == os.path.join(box.data, "vms")  # no pool yet: not written down
    assert places.recorded("vms") == "" and pool_places.iso_dir(box.data) == ""
    box.rows.append({"name": "tank", "mountpoint": box.tank, "ejected": False})
    want = os.path.join(box.tank, "vms")
    assert pool_places.vms_root(box.data) == want and places.recorded("vms") == want
    assert pool_places.iso_dir(box.data) == os.path.join(want, "isos")
    monkeypatch.setattr(vm_store, "DATA_DIR", box.data)
    assert vm_store.vm_file("win11", "disk.qcow2") == os.path.join(want, "win11", "disk.qcow2")
    disk = os.path.join(want, "win11", "disk.qcow2")
    os.makedirs(os.path.dirname(disk))
    open(disk, "w").close()
    assert vm_store._confined(disk, vm_store._vm_disk_roots(), "file") == os.path.realpath(disk)
    monkeypatch.setattr(vm_host, "DATA_DIR", box.data)
    assert vm_host._get_target_iso_dir() == os.path.join(want, "isos")
    assert vm_host.iso_dirs()[0] == os.path.join(want, "isos")


def test_machines_already_in_the_data_folder_stay(box):
    os.makedirs(os.path.join(box.data, "vms", "old-vm"))
    os.makedirs(os.path.join(box.data, "vms", "isos"))
    box.rows.append({"name": "tank", "mountpoint": box.tank, "ejected": False})
    assert pool_places.vms_root(box.data) == os.path.join(box.data, "vms")
    assert places.recorded("vms") == os.path.join(box.data, "vms") and pool_places.iso_dir(box.data) == ""


def test_elsewhere_the_data_folder(box, monkeypatch):
    monkeypatch.setattr(runtime, "MANAGED_MARK", os.path.join(box.data, "no-mark"))
    box.rows.append({"name": "tank", "mountpoint": box.tank, "ejected": False})
    assert pool_places.vms_root(box.data) == os.path.join(box.data, "vms") and places.recorded("vms") == ""
    assert pool_places._has_machines(os.path.join(box.data, "missing")) is False
