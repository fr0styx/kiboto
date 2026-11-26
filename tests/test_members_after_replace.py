"""After a drive was replaced from the app, the pool's record names the drives it is on now."""

import os

from backend.hardware.pal import generic_linux as gl
from backend.hardware.pal import pool_registry


def _record(tmp_path, monkeypatch, fs, members):
    monkeypatch.setattr(pool_registry, "DATA_DIR", str(tmp_path))
    pool_registry.record("media", fs, "raid1", "0d68d8be-7771-40fb-bdc4-ea56c44ae2f6", members, "/mnt/storage/media")


def test_the_replaced_drive_goes_and_the_new_one_comes(tmp_path, monkeypatch):
    _record(tmp_path, monkeypatch, "zfs", ["/dev/disk/by-id/virtio-KBTESTDISK1", "/dev/disk/by-id/virtio-KBTESTDISK6"])
    got = gl.members_after_replace(
        "media", "/dev/disk/by-id/virtio-KBTESTDISK6-part1", "/dev/disk/by-id/virtio-KBTESTDISK4"
    )
    assert got == ["/dev/disk/by-id/virtio-KBTESTDISK1", "/dev/disk/by-id/virtio-KBTESTDISK4"]
    assert pool_registry.find("media")["members"] == got
    assert gl.members_after_replace("nothing", "a", "b") is None


def test_a_missing_btrfs_drive_is_the_one_the_kernel_no_longer_lists(tmp_path, monkeypatch):
    dev = tmp_path / "dev"
    dev.mkdir()
    (dev / "vdd").write_text("")
    (dev / "vde").write_text("")
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    os.symlink(dev / "vdd", by_id / "virtio-KBTESTDISK3")
    os.symlink(dev / "vde", by_id / "virtio-KBTESTDISK4")
    _record(tmp_path, monkeypatch, "btrfs", [str(by_id / "virtio-KBTESTDISK3"), str(by_id / "virtio-KBTESTDISK4")])
    monkeypatch.setattr(gl, "btrfs_sysfs", lambda uuid: (["vdd"], True))
    got = gl.members_after_replace("media", "missing drive 2", "/dev/disk/by-id/virtio-KBTESTDISK2")
    assert got == [str(by_id / "virtio-KBTESTDISK3"), "/dev/disk/by-id/virtio-KBTESTDISK2"]


def test_the_record_follows_only_a_started_replacement(monkeypatch):
    seen = []
    monkeypatch.setattr(gl, "members_after_replace", lambda *a: seen.append(a))
    adapter = gl.GenericLinuxStorageAdapter.__new__(gl.GenericLinuxStorageAdapter)
    monkeypatch.setattr(gl, "_through_door", lambda op, here, **kw: {"started": True, "old": "o", "new": "n"})
    adapter.replace_drive("media", "o", "n")
    monkeypatch.setattr(gl, "_through_door", lambda op, here, **kw: {"started": False, "why": "busy"})
    adapter.replace_drive("media", "o", "n")
    assert seen == [("media", "o", "n")]
