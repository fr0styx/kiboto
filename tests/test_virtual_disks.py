"""A virtual machine's disks (virtio, Xen, QEMU/VMware/VirtualBox/Hyper-V models) have no SMART and
never spin down: asked with -d sat, smartctl said "Device is in SLEEP mode" for them, and Kiboto OS in
a virtual machine held every folder and Recycle Bin back as being on a sleeping disk."""

import os

from backend.hardware import disks
from backend.hardware.smart_power import virtual_disk
from backend.state import Z_STATE


def _sys(tmp_path, name, vendor="", model=""):
    d = tmp_path / "block" / name / "device"
    d.mkdir(parents=True)
    (d / "vendor").write_text(vendor + "\n")
    (d / "model").write_text(model + "\n")
    (tmp_path / "block" / name / "removable").write_text("0\n")


def test_virtual_disks_are_known_by_name_or_model(tmp_path):
    _sys(tmp_path, "sda", "QEMU", "QEMU HARDDISK")
    _sys(tmp_path, "sdb", "ATA", "WDC WD80EFZZ-68B")
    _sys(tmp_path, "sdc", "Msft", "Virtual Disk")
    _sys(tmp_path, "sdd", "VMware", "Virtual disk")
    assert virtual_disk("vda", str(tmp_path)) and virtual_disk("xvdb", str(tmp_path))
    assert (
        virtual_disk("sda", str(tmp_path)) and virtual_disk("sdc", str(tmp_path)) and virtual_disk("sdd", str(tmp_path))
    )
    assert not virtual_disk("sdb", str(tmp_path)) and not virtual_disk("sdz", str(tmp_path))


def test_the_poller_never_asks_smartctl_about_a_virtual_disk(tmp_path, monkeypatch):
    _sys(tmp_path, "sda", "QEMU", "QEMU HARDDISK")
    monkeypatch.setattr(disks, "HOST_SYS", str(tmp_path))
    monkeypatch.setattr(disks, "_resolve_dev_path", lambda name: f"/dev/{name}")

    def no_smartctl(*a, **k):
        raise AssertionError("smartctl asked about a virtual disk")

    monkeypatch.setattr(disks.smart_read, "run", no_smartctl)
    disks.poll_disk_smart("sda", False)
    assert Z_STATE.cached_smart_data["sda"][1] == "ok"
    disks.poll_disk_smart("vdb", False)
    assert Z_STATE.cached_smart_data["vdb"][1] == "ok"


def test_readings_say_which_disks_are_virtual(tmp_path, monkeypatch):
    _sys(tmp_path, "sda", "QEMU", "QEMU HARDDISK")
    _sys(tmp_path, "sdb", "ATA", "ST4000VN006")
    monkeypatch.setattr(disks, "HOST_SYS", str(tmp_path))
    monkeypatch.setattr(
        disks, "_discover_disks", lambda: [{"dev": "sda", "role": "data"}, {"dev": "sdb", "role": "data"}]
    )
    got = {d["dev"]: d["virtual"] for d in disks.read_disk_temps_and_io()}
    assert got == {"sda": True, "sdb": False}
    assert os.path.isdir(tmp_path / "block")
