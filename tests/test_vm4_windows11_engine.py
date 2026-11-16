"""SET-29 stage 4 (Windows 11): new UEFI machines get q35 with SMM; a driver disc goes beside the installer."""

from backend.api import vms
from backend.services import vm_host, vm_qemu, vm_store
from tests.test_vm_qemu_launch import args, host, vm  # noqa: F401  (host is a fixture)


def test_q35_and_the_driver_disc_reach_qemu(host, monkeypatch):  # noqa: F811
    code = host["tmp"] / "OVMF_CODE_4M.ms.fd"
    code.write_text("")
    varsf = host["tmp"] / "OVMF_VARS_4M.ms.fd"
    varsf.write_text("")
    monkeypatch.setattr(vm_host, "_find_ovmf_firmware", lambda: (str(code), str(varsf)))
    win = host["tmp"] / "Win11.iso"
    win.write_text("")
    drivers = host["tmp"] / "virtio-win.iso"
    drivers.write_text("")
    target = vm(
        host["tmp"], firmware="uefi", machine="q35", iso_path=str(win), driver_iso_path=str(drivers), tpm_enabled=False
    )
    assert vm_qemu._start_qemu(target, 5903)[0]
    line = args(host["started"][0])
    assert "-machine q35,smm=on -global driver=cfi.pflash01,property=secure,value=on" in line
    assert f"-cdrom {win}" in line
    assert f"file={drivers},media=cdrom,readonly=on,if=none,id=drivercd -device ide-cd,drive=drivercd" in line


def test_older_machines_keep_their_chipset_and_a_missing_disc_is_left_out(host):  # noqa: F811
    target = vm(host["tmp"], firmware="uefi", driver_iso_path=str(host["tmp"] / "gone.iso"))
    assert vm_qemu._start_qemu(target, 5904)[0]
    line = args(host["started"][0])
    assert "-machine" not in line and "drivercd" not in line
    assert vm_qemu._driver_disc_args("vm-x", {}) == []


def test_the_disc_must_be_in_the_iso_folders(monkeypatch):
    monkeypatch.setattr(vm_store, "_confined", lambda path, roots, kind: None)
    assert vm_qemu._driver_disc_args("vm-x", {"driver_iso_path": "/etc/passwd"}) == []


def test_create_stores_the_chipset_and_disc_and_edit_changes_the_disc(client, auth_headers, monkeypatch):
    monkeypatch.setattr(vm_store, "_validate_vm_inputs", lambda *a, **k: None)
    base = {"os_family": "windows", "vcpus": 2, "ram_gb": 1.0, "disk_size_gb": 10, "override_limits": True}
    r = client.post(
        "/api/vms",
        json={**base, "name": "win11-a", "firmware": "uefi", "driver_iso_path": "/mnt/user/isos/virtio-win.iso"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["machine"] == "q35" and a["driver_iso_path"] == "/mnt/user/isos/virtio-win.iso"
    r = client.post("/api/vms", json={**base, "name": "old-bios"}, headers=auth_headers)
    b = r.json()
    assert b["machine"] == "pc" and b["driver_iso_path"] is None
    r = client.put(f"/api/vms/{a['id']}", json={"driver_iso_path": None}, headers=auth_headers)
    assert r.status_code == 200, r.text
    stored = next(v for v in vms._load_vms() if v["id"] == a["id"])
    assert stored["driver_iso_path"] is None
    for v in (a, b):
        client.delete(f"/api/vms/{v['id']}", headers=auth_headers)
