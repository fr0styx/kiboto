"""A btrfs mirror that lost a drive names the drive, instead of every drive reading OK."""

from backend.hardware.pal.base import PoolMember
from backend.hardware.pal.generic_linux import btrfs_missing_members

# what btrfs-progs 6.14 on Debian 13 printed for a mirror mounted without one of its two drives
SHOWN = """Label: 'media'  uuid: 0d68d8be-7771-40fb-bdc4-ea56c44ae2f6
\tTotal devices 2 FS bytes used 144.00KiB
\tdevid    1 size 8.00GiB used 1.28GiB path /dev/vdd
\tdevid    2 size 0 used 0 path  MISSING
"""


def member(dev):
    return PoolMember(name=dev, device=dev, id=dev, status="OK")


def test_the_drive_btrfs_no_longer_lists_is_the_missing_one():
    out = btrfs_missing_members([member("vdd"), member("vde")], SHOWN)
    assert [(m.device, m.status) for m in out] == [("vdd", "OK"), ("vde", "MISSING")]


def test_a_partition_counts_for_its_disk_and_nothing_listed_changes_nothing():
    shown = SHOWN.replace("/dev/vdd", "/dev/sdb1")
    out = btrfs_missing_members([member("sdb"), member("sdc")], shown)
    assert [(m.device, m.status) for m in out] == [("sdb", "OK"), ("sdc", "MISSING")]
    same = [member("vdd")]
    assert btrfs_missing_members(same, "nothing useful") == same
