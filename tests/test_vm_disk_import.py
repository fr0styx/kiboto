"""Re-audit R8: a machine can start from a disk made by VMware, Hyper-V or VirtualBox."""

import json
import shutil
import subprocess

import pytest

from backend.services import vm_host, vm_store


def test_disks_of_other_systems_are_offered_next_to_qcow2(tmp_path, monkeypatch):
    for name in ("win11.vmdk", "server.VHDX", "old.vhd", "box.vdi", "haos.qcow2", "setup.iso", "notes.txt"):
        (tmp_path / name).write_bytes(b"1")
    monkeypatch.setattr(vm_host, "iso_dirs", lambda: [str(tmp_path)])
    names = sorted(d["name"] for d in vm_host.scan_disk_images(lambda d: False))
    assert names == ["box.vdi", "haos.qcow2", "old.vhd", "server.VHDX", "win11.vmdk"]
    assert [d["name"] for d in vm_host.scan_isos(lambda d: False)] == ["setup.iso"]


def test_a_disk_bigger_than_the_size_asked_for_is_not_shrunk(tmp_path, monkeypatch):
    image = tmp_path / "big.vmdk"
    image.write_bytes(b"x")
    monkeypatch.setattr(vm_store, "_confined", lambda p, roots, kind: p)
    calls = []

    def run(cmd, **kw):
        calls.append(cmd[1])
        if cmd[1] == "info":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"virtual-size": 100 * 1024**3}), stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    vm_store.make_primary_disk(
        {"disk_image_path": str(image), "disk_size_gb": 32}, str(tmp_path / "d.qcow2"), "qemu-img", run
    )
    assert calls == ["convert", "info"]  # 100 GB stays 100 GB: shrinking would cut the system off
    calls.clear()
    vm_store.make_primary_disk(
        {"disk_image_path": str(image), "disk_size_gb": 200}, str(tmp_path / "d.qcow2"), "qemu-img", run
    )
    assert calls == ["convert", "info", "resize"]


def test_an_unreadable_size_grows_as_before(tmp_path, monkeypatch):
    image = tmp_path / "x.qcow2"
    image.write_bytes(b"x")
    monkeypatch.setattr(vm_store, "_confined", lambda p, roots, kind: p)
    calls = []

    def run(cmd, **kw):
        calls.append(cmd[1])
        if cmd[1] == "info":
            return subprocess.CompletedProcess(cmd, 0, stdout="not json", stderr="")
        return None

    vm_store.make_primary_disk({"disk_image_path": str(image)}, str(tmp_path / "d.qcow2"), "qemu-img", run)
    assert calls == ["convert", "info", "resize"]


@pytest.mark.skipif(shutil.which("qemu-img") is None, reason="qemu-img is not installed here")
@pytest.mark.parametrize("fmt, ext", [("vmdk", ".vmdk"), ("vhdx", ".vhdx"), ("vdi", ".vdi"), ("vpc", ".vhd")])
def test_real_disks_of_other_systems_become_a_qcow2_of_the_right_size(tmp_path, monkeypatch, fmt, ext):
    image = tmp_path / f"machine{ext}"
    subprocess.run(["qemu-img", "create", "-f", fmt, str(image), "64M"], check=True, capture_output=True)
    monkeypatch.setattr(vm_store, "_confined", lambda p, roots, kind: p)
    disk = tmp_path / "disk.qcow2"
    vm_store.make_primary_disk({"disk_image_path": str(image), "disk_size_gb": 1}, str(disk), "qemu-img")
    info = json.loads(
        subprocess.run(
            ["qemu-img", "info", "--output=json", str(disk)], check=True, capture_output=True, text=True
        ).stdout
    )
    assert info["format"] == "qcow2" and info["virtual-size"] == 1024**3
    assert image.exists()  # the original stays
