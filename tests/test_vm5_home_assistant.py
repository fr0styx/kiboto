"""VMs decision 5, third preset: Home Assistant OS as a ready-made disk from the catalog."""

import hashlib
import io
import lzma
import os

import pytest

from backend.api import vms
from backend.services import vm_host, vm_store


def test_unpack_streams_and_removes_the_archive(tmp_path):
    xz = tmp_path / "haos.qcow2.xz"
    xz.write_bytes(lzma.compress(b"QFI\xfb" + b"x" * 100))
    out = vm_store.unpack_xz(str(xz))
    assert out == str(tmp_path / "haos.qcow2") and (tmp_path / "haos.qcow2").read_bytes().startswith(b"QFI")
    assert not xz.exists() and not os.path.exists(out + ".unpacking")


def test_a_broken_archive_leaves_nothing_half_done(tmp_path):
    xz = tmp_path / "bad.qcow2.xz"
    xz.write_bytes(b"not xz at all")
    with pytest.raises(lzma.LZMAError):
        vm_store.unpack_xz(str(xz))
    assert xz.exists() and not (tmp_path / "bad.qcow2").exists() and not (tmp_path / "bad.qcow2.unpacking").exists()
    other = tmp_path / "plain.bin"
    other.write_bytes(lzma.compress(b"y"))
    assert vm_store.unpack_xz(str(other)).endswith("plain.bin.unpacked")


def test_the_first_disk_is_a_grown_copy_of_the_ready_made_disk(tmp_path, monkeypatch):
    image = tmp_path / "haos_ova-18.4.qcow2"
    image.write_bytes(b"QFI")
    monkeypatch.setattr(vm_store, "_confined", lambda p, roots, kind: p)
    calls = []
    run = lambda cmd, **kw: calls.append(cmd)  # noqa: E731
    vm_store.make_primary_disk(
        {"disk_image_path": str(image), "disk_size_gb": 40}, str(tmp_path / "disk.qcow2"), "qemu-img", run
    )
    assert calls == [
        ["qemu-img", "convert", "-O", "qcow2", str(image), str(tmp_path / "disk.qcow2")],
        ["qemu-img", "info", "--output=json", str(tmp_path / "disk.qcow2")],  # never shrink (re-audit R8)
        ["qemu-img", "resize", str(tmp_path / "disk.qcow2"), "40G"],
    ]
    calls.clear()
    vm_store.make_primary_disk({}, "d.qcow2", "qemu-img", run)
    assert calls == [["qemu-img", "create", "-f", "qcow2", "d.qcow2", "32G"]]
    with pytest.raises(ValueError):
        vm_store.make_primary_disk({"disk_image_path": str(tmp_path / "gone.qcow2")}, "d.qcow2", "qemu-img", run)
    monkeypatch.setattr(vm_store, "_confined", lambda p, roots, kind: None)
    with pytest.raises(ValueError):
        vm_store.make_primary_disk({"disk_image_path": str(image)}, "d.qcow2", "qemu-img", run)


def test_ready_made_disks_are_listed_apart_from_installers(tmp_path, monkeypatch):
    (tmp_path / "a.iso").write_bytes(b"1")
    (tmp_path / "haos_ova-18.4.qcow2").write_bytes(b"22")
    monkeypatch.setattr(vm_host, "iso_dirs", lambda: [str(tmp_path)])
    awake = lambda d: False  # noqa: E731
    assert [d["name"] for d in vm_host.scan_disk_images(awake)] == ["haos_ova-18.4.qcow2"]
    assert [d["name"] for d in vm_host.scan_isos(awake)] == ["a.iso"]


class _Resp(io.BytesIO):
    status = 200
    headers = {"Content-Length": "0"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_download_is_checked_then_unpacked(tmp_path, monkeypatch):
    payload = lzma.compress(b"QFI\xfb disk")
    item = {
        "name": "Home Assistant OS",
        "filename": "haos.qcow2.xz",
        "download_url": "https://github.com/x",
        "unpack": "xz",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    monkeypatch.setattr("backend.services.safe_fetch.safe_open", lambda url, **kw: _Resp(payload))
    # setitem: removed afterwards; a task left behind broke the jobs list for a later test (random order, seed 629288)
    monkeypatch.setitem(vms._DOWNLOAD_TASKS, "t1", {"status": "downloading"})
    vms._download_iso_worker("t1", item, str(tmp_path))
    assert vms._DOWNLOAD_TASKS["t1"]["status"] == "completed"
    assert vms._DOWNLOAD_TASKS["t1"]["path"] == str(tmp_path / "haos.qcow2")
    assert (tmp_path / "haos.qcow2").read_bytes() == b"QFI\xfb disk" and not (tmp_path / "haos.qcow2.xz").exists()


def test_the_catalog_entry_and_its_present_check(client, auth_headers, tmp_path, monkeypatch):
    item = next(c for c in vm_store.OFFICIAL_ISO_CATALOG if c["id"] == "haos")
    assert item["download_url"].startswith("https://github.com/home-assistant/operating-system/releases/download/")
    assert len(item["sha256"]) == 64 and item["unpack"] == "xz"
    monkeypatch.setattr(vm_host, "_get_target_iso_dir", lambda: str(tmp_path))
    (tmp_path / "haos_ova-18.4.qcow2").write_bytes(b"QFI")
    r = client.post("/api/vms/catalog/haos/download", headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "already_present"
    monkeypatch.setattr(vm_host, "scan_disk_images", lambda: [{"name": "haos_ova-18.4.qcow2", "path": "/x"}])
    # called directly: the test client's schema check reads /vms/disk-images as /vms/{vm_id}
    assert vms.list_disk_images()[0]["name"] == "haos_ova-18.4.qcow2"


def test_create_keeps_the_ready_made_disk(client, auth_headers, monkeypatch):
    monkeypatch.setattr(vm_store, "_validate_vm_inputs", lambda *a, **k: None)
    body = {
        "name": "home-assistant",
        "os_family": "linux",
        "vcpus": 2,
        "ram_gb": 1.0,
        "disk_size_gb": 32,
        "firmware": "uefi",
        "override_limits": True,
        "disk_image_path": "/mnt/user/isos/haos_ova-18.4.qcow2",
    }
    r = client.post("/api/vms", json=body, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["disk_image_path"] == "/mnt/user/isos/haos_ova-18.4.qcow2" and r.json()["machine"] == "q35"
    client.delete(f"/api/vms/{r.json()['id']}", headers=auth_headers)
