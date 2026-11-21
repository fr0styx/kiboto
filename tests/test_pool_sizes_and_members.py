"""What a pool list says about size and drives is true.

Found with real tools: a raidz1 of three 8 GB drives showed 23.5 GB (zpool counts parity), and the
main pool, there a plain folder on the system disk, listed all six data drives as its members."""

import pytest

from backend.hardware.pal.base import PoolMember
from backend.hardware.pal_storage import GenericLinuxStorageAdapter

GB = 1024**3


def _disks(*names):
    return [PoolMember(name=n, device=n, id=n.upper()) for n in names]


@pytest.fixture
def nas(tmp_path):
    adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path))
    adapter._discover_hal_disks = lambda: _disks("sda", "sdb", "sdc", "sdd")
    adapter._parse_mdstat = lambda: {}
    adapter._parse_mounts = lambda: []
    adapter._parse_zpool_members = lambda name: []
    return adapter


def _answers(nas, table):
    def run(cmd):
        for start, answer in table.items():
            if " ".join(cmd).startswith(start):
                return answer
        return 1, "", ""

    nas._run_cmd = run


def _pool(nas, pid):
    return next(p for p in nas.list_pools() if p.id == pid)


def test_a_raidz_pool_shows_what_can_be_stored(nas):
    _answers(
        nas,
        {
            "zpool list": (0, f"tank\t{24 * GB}\t{3 * GB}\t{21 * GB}\tONLINE\n", ""),
            "zfs list -Hp -o used,avail tank": (0, f"{2 * GB}\t{14 * GB}\n", ""),
            "zpool status": (0, "  raidz1-0  ONLINE\n", ""),
            "zfs get": (0, "/mnt/tank\n", ""),
        },
    )
    tank = _pool(nas, "tank")
    assert (tank.total_bytes, tank.used_bytes, tank.free_bytes, tank.used_pct) == (16 * GB, 2 * GB, 14 * GB, 12.5)


def test_without_the_datasets_numbers_the_pools_own_stay(nas):
    _answers(
        nas,
        {
            "zpool list": (0, f"tank\t{8 * GB}\t{1 * GB}\t{7 * GB}\tONLINE\n", ""),
            "zfs list": (1, "", "dataset is busy"),
            "zpool status": (0, "  mirror-0  ONLINE\n", ""),
            "zfs get": (0, "/mnt/tank\n", ""),
        },
    )
    assert _pool(nas, "tank").total_bytes == 8 * GB


@pytest.mark.parametrize(
    "findmnt, btrfs_show, want",
    [
        ((0, "/dev/sdb1 ext4\n", ""), (1, "", ""), ["sdb"]),  # a file system of its own, on one drive
        (
            (0, "/dev/sdc[/@shares] btrfs\n", ""),
            (0, "\tdevid 1 size 8G used 1G path /dev/sdc\n\tdevid 2 size 8G used 1G path /dev/sdd\n", ""),
            ["sdc", "sdd"],
        ),
        (
            (0, "/dev/sdc[/@shares] btrfs\n", ""),
            (1, "", "not mounted"),
            ["sdc"],
        ),  # btrfs does not answer: the device it is mounted from
        ((0, "/dev/vda1 ext4\n", ""), (1, "", ""), []),  # a folder on the system disk: no data drive is under it
        ((0, "tank/data zfs\n", ""), (1, "", ""), []),  # a dataset: its pool has its own entry
        ((1, "", ""), (1, "", ""), []),  # nothing known: nothing claimed
    ],
)
def test_the_main_pool_lists_only_the_drives_under_it(nas, findmnt, btrfs_show, want):
    _answers(nas, {"findmnt -rno SOURCE,FSTYPE --target": findmnt, "btrfs filesystem show": btrfs_show})
    assert [m.device for m in _pool(nas, "default_pool").members] == want
