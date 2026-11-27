"""A new pool is made with a layout its kind has, by the name its record keeps. ZFS took "raid1"
(the API's default), "raid10" or "raid5" and made a stripe with no copy that its record then called
protected; ext4 recorded "raid1" for its one drive."""

import pytest

from backend.hardware.pal import pool_rules
from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter


@pytest.mark.parametrize(
    ("fs", "asked", "drives", "made"),
    [
        ("zfs", "raid1", 2, "mirror"),
        ("zfs", "MIRROR", 2, "mirror"),
        ("zfs", "stripe", 2, "single"),
        ("zfs", "raid0", 1, "single"),
        ("zfs", "raidz2", 4, "raidz2"),
        ("btrfs", "mirror", 2, "raid1"),
        ("btrfs", "raid1c3", 3, "raid1c3"),
        ("btrfs", "jbod", 1, "single"),
        ("ext4", "single", 1, "single"),
    ],
)
def test_layouts_by_their_names(fs, asked, drives, made):
    assert pool_rules.pool_layout(fs, asked, drives) == made


@pytest.mark.parametrize(
    ("fs", "asked", "drives", "says"),
    [
        ("zfs", "raid10", 4, "made as one of"),
        ("zfs", "raid5", 3, "made as one of"),
        ("zfs", "raid1", 1, "OpenZFS Mirror requires at least 2 disks"),
        ("btrfs", "raidz1", 3, "made as one of"),
        ("btrfs", "raid1c4", 3, "RAID1C4 requires at least 4 disks"),
        ("ext4", "raid1", 1, "made as one of"),
        ("ext4", "single", 2, "one drive"),
        ("xfs", "single", 1, "ZFS, btrfs and ext4"),
        ("zfs", "", 2, "Not nothing"),
    ],
)
def test_other_layouts_are_refused(fs, asked, drives, says):
    with pytest.raises(ValueError, match=says):
        pool_rules.pool_layout(fs, asked, drives)


def test_zfs_raid1_is_made_as_a_mirror_and_recorded_as_one(tmp_path, monkeypatch):
    adapter = GenericLinuxStorageAdapter()
    adapter._resolve_disk_path = lambda d: "/dev/" + d  # never the machine running the tests
    ran = []
    adapter._run_cmd = lambda cmd: (ran.append(cmd), (0, "", ""))[1]
    recorded = {}
    monkeypatch.setattr(
        "backend.hardware.pal.pool_registry.record",
        lambda name, fs, profile, *a, **k: recorded.update(name=name, profile=profile),
    )
    res = adapter.create_pool(
        name="tank", fs_type="zfs", profile="raid1", disks=["sda", "sdb"], mountpoint=str(tmp_path / "tank")
    )
    create = next(c for c in ran if c[:2] == ["zpool", "create"])
    assert create[-3:] == ["mirror", "/dev/sda", "/dev/sdb"]
    assert res["profile"] == "mirror" and recorded["profile"] == "mirror"


def test_a_zfs_stripe_is_named_single_and_has_no_layout_word(tmp_path, monkeypatch):
    adapter = GenericLinuxStorageAdapter()
    adapter._resolve_disk_path = lambda d: "/dev/" + d  # never the machine running the tests
    ran = []
    adapter._run_cmd = lambda cmd: (ran.append(cmd), (0, "", ""))[1]
    monkeypatch.setattr("backend.hardware.pal.pool_registry.record", lambda *a, **k: None)
    adapter.create_pool(
        name="tank", fs_type="zfs", profile="single", disks=["sda", "sdb"], mountpoint=str(tmp_path / "tank")
    )
    create = next(c for c in ran if c[:2] == ["zpool", "create"])
    assert create[-3:] == ["tank", "/dev/sda", "/dev/sdb"]
