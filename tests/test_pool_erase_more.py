"""Deleting a pool on a machine Kiboto manages.

Found with real tools: an ext4 pool Kiboto had made could not be deleted at all ("delete this one in
the host's own settings", which such a machine does not have), and after a ZFS pool was erased its
drives still read as "contains data", because the partition table ZFS had written stayed."""

from types import SimpleNamespace

import pytest

from backend.hardware.pal import pool_erase as pe
from backend.hardware.pal import pool_registry as reg


def pool(**kw):
    base = {"id": "docs", "name": "docs", "fs_type": "ext4", "pool_type": "single", "mountpoint": "/mnt/pools/docs"}
    return SimpleNamespace(**(base | kw))


def runner(answers):
    calls = []

    def run(cmd):
        calls.append(cmd)
        for prefix, ans in answers:
            if cmd[: len(prefix)] == prefix:
                return ans
        return (0, "", "")

    run.calls = calls
    return run


def test_an_ext4_pool_is_erasable_only_when_kiboto_recorded_it():
    assert pe.kind_of(pool()) == ""  # a plain ext4 disk Kiboto knows nothing about
    reg.record("docs", "ext4", "single", "e-1", ["/dev/sdf"], "/mnt/pools/docs")
    assert pe.kind_of(pool()) == "ext4"


def test_ext4_plan_and_erase():
    reg.record("docs", "ext4", "single", "e-1", ["/dev/sdf"], "/mnt/pools/docs")
    run = runner(
        [
            (["findmnt"], (0, "e-1 /dev/sdf\n", "")),
            (["blkid", "-p", "-o", "export", "/dev/sdf"], (0, "DEVNAME=/dev/sdf\nUUID=e-1\nTYPE=ext4\n", "")),
        ]
    )
    p = pe.plan(pool(), run)
    assert (p["kind"], p["id"], p["drives"], p["whole_disks"]) == ("ext4", "e-1", ["/dev/sdf"], [])
    assert pe.execute(p, run) == ["/dev/sdf"]
    assert run.calls[-2:] == [["umount", "/mnt/pools/docs"], ["wipefs", "-a", "/dev/sdf"]]


@pytest.mark.parametrize(
    "mounted, on_disk",
    [
        ((1, "", ""), "UUID=e-1\nTYPE=ext4\n"),  # not mounted
        ((0, "other /dev/sdf\n", ""), "UUID=e-1\nTYPE=ext4\n"),  # another file system on its folder
        ((0, "e-1 /dev/sdf\n", ""), "UUID=e-1\nTYPE=xfs\n"),  # the drive holds another kind
        ((0, "e-1 /dev/sdf\n", ""), "UUID=zzz\nTYPE=ext4\n"),  # the drive holds another ext4
    ],
)
def test_ext4_is_refused_when_it_cannot_be_confirmed(mounted, on_disk):
    reg.record("docs", "ext4", "single", "e-1", ["/dev/sdf"], "/mnt/pools/docs")
    run = runner([(["findmnt"], mounted), (["blkid"], (0, on_disk, ""))])
    with pytest.raises(pe.EraseRefused):
        pe.plan(pool(), run)
    assert not [c for c in run.calls if c[0] in ("umount", "wipefs")]


RESERVED = "6a945a3b-1dd2-11b2-99a6-080020736631"


def _zfs(lsblk_kids):
    return runner(
        [
            (["zpool", "get"], (0, "77\n", "")),
            (["zpool", "status"], (0, "\ttank\n\t  mirror-0\n\t    /dev/sdb1  ONLINE\n\t    /dev/sdc1  ONLINE\n", "")),
            (["zdb", "-l"], (0, "    pool_guid: 77\n", "")),
            (["lsblk", "-ndo", "PKNAME", "/dev/sdb1"], (0, "sdb\n", "")),
            (["lsblk", "-ndo", "PKNAME", "/dev/sdc1"], (0, "sdc\n", "")),
            (["lsblk", "-rno", "PATH,TYPE,PARTTYPE", "/dev/sdb"], (0, lsblk_kids("sdb"), "")),
            (["lsblk", "-rno", "PATH,TYPE,PARTTYPE", "/dev/sdc"], (0, lsblk_kids("sdc"), "")),
        ]
    )


def test_a_zfs_erase_takes_the_partition_table_of_drives_it_had_whole():
    run = _zfs(
        lambda d: f"/dev/{d} disk \n/dev/{d}1 part 6a898cc3-1dd2-11b2-99a6-080020736631\n/dev/{d}9 part {RESERVED}\n"
    )
    tank = pool(id="tank", name="tank", fs_type="zfs", pool_type="zfs_pool", mountpoint="/mnt/tank")
    p = pe.plan(tank, run)
    assert p["whole_disks"] == ["/dev/sdb", "/dev/sdc"]
    pe.execute(p, run)
    wiped = [c[-1] for c in run.calls if c[:2] == ["wipefs", "-a"]]
    assert wiped == ["/dev/sdb1", "/dev/sdc1", "/dev/sdb", "/dev/sdc"]  # the table after its partitions


def test_a_drive_that_holds_something_else_keeps_its_partition_table():
    run = _zfs(lambda d: f"/dev/{d} disk \n/dev/{d}1 part aaaa\n/dev/{d}2 part 0fc63daf-8483-4772-8e79-3d69d8477de4\n")
    tank = pool(id="tank", name="tank", fs_type="zfs", pool_type="zfs_pool", mountpoint="/mnt/tank")
    p = pe.plan(tank, run)
    assert p["whole_disks"] == []
    pe.execute(p, run)
    assert [c[-1] for c in run.calls if c[:2] == ["wipefs", "-a"]] == ["/dev/sdb1", "/dev/sdc1"]


def test_the_adapter_reports_the_cleared_drives(tmp_path, monkeypatch):
    from backend.hardware.pal_storage import GenericLinuxStorageAdapter

    adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path))
    adapter._run_cmd = lambda cmd: (0, "", "")
    tank = pool(id="tank", name="tank", fs_type="zfs", pool_type="zfs_pool", mountpoint="")
    monkeypatch.setattr(adapter, "resolve_pool", lambda pid: tank)
    monkeypatch.setattr(adapter, "_no_merged_folder", lambda p: None)
    monkeypatch.setattr(
        pe,
        "plan",
        lambda p, run: {
            "pool": "tank",
            "kind": "zfs",
            "drives": ["/dev/sdb1"],
            "whole_disks": ["/dev/sdb"],
            "mountpoint": "",
        },
    )
    monkeypatch.setattr(pe, "execute", lambda p, run: p["drives"])
    assert adapter.erase_pool("tank") == {
        "status": "erased",
        "pool_id": "tank",
        "drives": ["/dev/sdb1"],
        "whole_disks": ["/dev/sdb"],
    }
