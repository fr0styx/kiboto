"""USB disks on a machine set up for Kiboto: listed from lsblk, opened and ejected when asked."""

import json
import os

import pytest

from backend import runtime
from backend.hardware import usb_mount
from backend.hardware.pal import pool_registry

TREE = {
    "blockdevices": [
        {
            "name": "vda",
            "path": "/dev/vda",
            "tran": "virtio",
            "hotplug": False,
            "type": "disk",
            "fstype": None,
            "children": [{"name": "vda1", "path": "/dev/vda1", "type": "part", "fstype": "ext4", "mountpoints": ["/"]}],
        },
        {
            "name": "sda",
            "path": "/dev/sda",
            "tran": "usb",
            "hotplug": True,
            "type": "disk",
            "fstype": None,
            "children": [
                {
                    "name": "sda1",
                    "path": "/dev/sda1",
                    "type": "part",
                    "fstype": "exfat",
                    "label": "Holiday Pics!",
                    "uuid": "AB12",
                    "size": 64000000000,
                    "mountpoints": [None],
                },
                {"name": "sda2", "path": "/dev/sda2", "type": "part", "fstype": "crypto_LUKS", "mountpoints": [None]},
            ],
        },
        {
            "name": "sdb",
            "path": "/dev/sdb",
            "tran": "usb",
            "hotplug": True,
            "type": "disk",
            "fstype": "btrfs",
            "label": "media",
            "uuid": "u-media",
            "size": 1,
            "mountpoints": [None],
        },
        {
            "name": "sdc",
            "path": "/dev/sdc",
            "tran": "usb",
            "hotplug": True,
            "type": "disk",
            "fstype": None,
            "children": [
                {
                    "name": "sdc1",
                    "path": "/dev/sdc1",
                    "type": "part",
                    "fstype": "ext4",
                    "mountpoints": ["/mnt/storage/old"],
                }
            ],
        },
        {
            "name": "sdd",
            "path": "/dev/sdd",
            "tran": "sata",
            "hotplug": True,
            "type": "disk",
            "fstype": "ntfs",
            "label": "",
            "size": 5,
            "mountpoints": [],
        },
        {"name": "sde", "path": "/dev/sde", "tran": "sata", "hotplug": False, "type": "disk", "fstype": "zfs_member"},
    ]
}


@pytest.fixture
def box(tmp_path, monkeypatch):
    root = tmp_path / "disks"
    root.mkdir()
    monkeypatch.setattr(usb_mount, "ROOT", str(root))
    monkeypatch.setattr(pool_registry, "load", lambda: [{"name": "media", "disks": ["/dev/sdx"], "uuid": "u-media"}])
    mounted = set()
    real = os.path.ismount
    monkeypatch.setattr(os.path, "ismount", lambda p: str(p) in mounted or real(p))
    ran = []

    def do(cmd):
        ran.append(cmd)
        if cmd[0] == "lsblk":
            return 0, json.dumps(TREE), ""
        if cmd[0] == "mount":
            mounted.add(cmd[-1])
        if cmd[0] == "umount":
            mounted.discard(cmd[-1])
        return 0, "", ""

    return type("Box", (), {"root": str(root), "do": staticmethod(do), "ran": ran, "mounted": mounted})


def test_only_usable_usb_disks_are_offered(box):
    found = usb_mount.unmounted(box.do)
    assert [d["device"] for d in found] == ["/dev/sda1", "/dev/sdd"]
    assert found[0] == {"device": "/dev/sda1", "label": "Holiday Pics!", "fs": "exfat", "size_bytes": 64000000000}
    assert usb_mount.unmounted(lambda cmd: (1, "", "no lsblk")) == []
    assert usb_mount.unmounted(lambda cmd: (0, "not json", "")) == []


def test_open_and_eject(box):
    where = usb_mount.open_disk("/dev/sda1", box.do)
    assert where == os.path.join(box.root, "Holiday_Pics")
    assert box.ran[-1] == ["mount", "-o", "nosuid,nodev,noexec,uid=0,gid=100,umask=0002", "/dev/sda1", where]
    ntfs = usb_mount.open_disk("/dev/sdd", box.do)
    assert ntfs == os.path.join(box.root, "sdd") and box.ran[-1][3:5] == ["-t", "ntfs3"]
    with pytest.raises(ValueError):
        usb_mount.open_disk("/dev/sdb", box.do)  # a pool's disk
    usb_mount.eject(where, box.do)
    assert box.ran[-2:] == [["sync"], ["umount", where]] and not os.path.exists(where)
    with pytest.raises(ValueError):
        usb_mount.eject("/mnt/storage/tank", box.do)


def test_a_disk_that_will_not_mount_or_eject(box):
    def failing(cmd):
        if cmd[0] == "lsblk":
            return 0, json.dumps(TREE), ""
        return 32, "", "wrong fs type"

    with pytest.raises(RuntimeError, match="could not be opened"):
        usb_mount.open_disk("/dev/sda1", failing)
    assert os.listdir(box.root) == []
    where = usb_mount.open_disk("/dev/sda1", box.do)
    with pytest.raises(RuntimeError, match="still in use"):
        usb_mount.eject(where, failing)


def test_a_taken_name_gets_a_number(box):
    first = os.path.join(box.root, "Holiday_Pics")
    os.makedirs(first)
    open(os.path.join(first, "x"), "w").close()
    assert usb_mount.open_disk("/dev/sda1", box.do) == first + "-2"


def test_the_routes(box, client, auth_headers, monkeypatch, tmp_path):
    from backend.api import system

    r = client.post("/api/usb/open", headers=auth_headers, json={"device": "/dev/sda1"})
    assert r.status_code == 409  # a guest: the host opens disks
    assert client.post("/api/usb/eject", headers=auth_headers, json={"path": "/x"}).status_code == 409
    assert client.get("/api/usb/disks", headers=auth_headers).json()["opens_disks"] is False
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    monkeypatch.setattr(usb_mount, "run", box.do)
    got = client.get("/api/usb/disks", headers=auth_headers).json()
    assert got["opens_disks"] is True and [d["device"] for d in got["can_open"]] == ["/dev/sda1", "/dev/sdd"]
    r = client.post("/api/usb/open", headers=auth_headers, json={"device": "/dev/sda1"})
    assert r.status_code == 200 and r.json()["path"].endswith("Holiday_Pics")
    assert client.post("/api/usb/open", headers=auth_headers, json={"device": "/dev/sdb"}).status_code == 404
    assert client.post("/api/usb/eject", headers=auth_headers, json={"path": r.json()["path"]}).json() == {
        "status": "ejected"
    }
    assert client.post("/api/usb/eject", headers=auth_headers, json={"path": "/nope"}).status_code == 404
    monkeypatch.setattr(system.usb_mount, "open_disk", lambda d: (_ for _ in ()).throw(RuntimeError("bad")))
    assert client.post("/api/usb/open", headers=auth_headers, json={"device": "/dev/sda1"}).status_code == 502
    monkeypatch.setattr(system.usb_mount, "eject", lambda p: (_ for _ in ()).throw(RuntimeError("busy")))
    assert client.post("/api/usb/eject", headers=auth_headers, json={"path": "/x"}).status_code == 409


def test_the_real_runner():
    assert usb_mount.run(["true"])[0] == 0
    assert usb_mount.run(["/no/such/tool"])[0] == 1
