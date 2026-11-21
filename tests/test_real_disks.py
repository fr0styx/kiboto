"""Real storage tools on drives that hold nothing.

Every other storage test gives the adapter a pretend command runner. Here zpool, mkfs, mount, btrfs
and wipefs really run, on the drives named in KIBOTO_TEST_DISKS (the test machine's six empty disks)
or, without it, on loop devices over files (the CI runner). A pool of each kind Kiboto makes is
created, listed, checked, ejected, found, imported, lost and deleted.

It formats drives, so it runs only as root with KIBOTO_REAL_DISKS=1, on a machine made for it."""

import os
import pathlib
import subprocess

import pytest

from backend.hardware import disk_safety
from backend.hardware.pal import pool_registry
from backend.hardware.pal_storage import GenericLinuxStorageAdapter
from backend.services import pool_alerts

REAL = os.environ.get("KIBOTO_REAL_DISKS") == "1" and hasattr(os, "geteuid") and os.geteuid() == 0
pytestmark = [
    pytest.mark.real_storage_tools,
    pytest.mark.skipif(not REAL, reason="formats drives: needs root and KIBOTO_REAL_DISKS=1"),
]

ROOT = "/mnt/kbtest-real"  # where the pools are mounted: a folder on the machine's own system disk
KINDS = [
    ("zfs", "mirror", 2),
    ("zfs", "raidz1", 3),
    ("btrfs", "raid1", 2),
    ("btrfs", "single", 1),
    ("ext4", "single", 1),
]
IDS = [f"{fs}-{profile}" for fs, profile, _n in KINDS]


def sh(*cmd, check=True):
    r = subprocess.run(list(cmd), capture_output=True, text=True, timeout=180)
    if check and r.returncode != 0:
        raise AssertionError(f"{' '.join(cmd)}: {(r.stderr or r.stdout).strip()}")
    return r.stdout


def _clean(devs):
    for name in sh("zpool", "list", "-H", "-o", "name", check=False).split():
        if name.startswith("kbt"):
            sh("zpool", "destroy", "-f", name, check=False)
    if os.path.isdir(ROOT):
        for entry in os.listdir(ROOT):
            path = os.path.join(ROOT, entry)
            sh("umount", "-R", path, check=False)
            sh("chattr", "-i", path, check=False)
            sh("rmdir", path, check=False)
    for dev in devs:
        for part in reversed(sh("lsblk", "-rno", "PATH", dev, check=False).split()):
            sh("wipefs", "-a", part, check=False)
    sh("udevadm", "settle", check=False)


@pytest.fixture
def drives(tmp_path):
    named = [d for d in os.environ.get("KIBOTO_TEST_DISKS", "").split(",") if d]
    made = []
    if not named:
        for i in range(3):
            image = tmp_path / f"drive{i}.img"
            with open(image, "wb") as fh:
                fh.truncate(1 << 30)
            made.append(sh("losetup", "--find", "--show", str(image)).strip())
    devs = named or made
    os.makedirs(ROOT, exist_ok=True)
    _clean(devs)
    yield devs
    _clean(devs)
    for dev in made:
        sh("losetup", "-d", dev, check=False)


@pytest.fixture
def nas(drives):
    return GenericLinuxStorageAdapter(pool_path=ROOT)


def _make(nas, drives, fs, profile, n):
    name = "kbt" + fs + profile
    mount = f"{ROOT}/{name}"
    res = nas.create_pool(name=name, fs_type=fs, profile=profile, disks=drives[:n], mountpoint=mount)
    assert res["status"] == "provisioned" and os.path.ismount(mount)
    pathlib.Path(mount, "kept.txt").write_text("still here")
    return name, mount


def _listed(nas, name):
    return next((p for p in nas.list_pools() if p.id == name), None)


@pytest.mark.parametrize("fs, profile, n", KINDS, ids=IDS)
def test_a_pool_is_made_listed_checked_and_deleted(nas, drives, fs, profile, n):
    name, mount = _make(nas, drives, fs, profile, n)
    pool = _listed(nas, name)
    assert pool is not None, "a pool Kiboto made is not in its own list"
    assert (pool.fs_type, pool.fs_profile, pool.status, pool.mountpoint) == (fs, profile, "HEALTHY", mount)
    assert len(pool.members) == n and pool.total_bytes > 0
    assert pool.parity_protected is (profile != "single")
    row = pool_registry.find(name)
    assert row["uuid"] and len(row["members"]) == n
    if fs != "ext4":  # ext4 has no check of its own
        assert nas.trigger_scrub(name, "start")["status"] == "started"
        sh("zpool", "wait", "-t", "scrub", name) if fs == "zfs" else sh("btrfs", "scrub", "status", mount)
        if fs == "btrfs":
            nas.trigger_scrub(name, "cancel")
    assert nas.erase_pool(name)["status"] == "erased"
    assert _listed(nas, name) is None and pool_registry.find(name) is None
    assert not os.path.exists(mount)
    sh("udevadm", "settle", check=False)
    assert disk_safety.check_disks(drives[:n]) == [], "an erased drive must read as empty"


@pytest.mark.parametrize("fs, profile, n", KINDS, ids=IDS)
def test_an_ejected_pool_is_found_and_comes_back_with_its_files(nas, drives, fs, profile, n):
    name, mount = _make(nas, drives, fs, profile, n)
    assert nas.export_pool(name)["status"] == "exported"
    assert not os.path.ismount(mount) and _listed(nas, name) is None
    assert name in [p["pool_id"] for p in nas.discover_external_pools()]
    assert not [x for x in pool_alerts.problems(nas.list_pools()) if x["subject"] == name]  # away on purpose
    assert nas.import_pool(name, fs_type=fs)["status"] == "imported"
    assert pathlib.Path(mount, "kept.txt").read_text() == "still here"
    assert _listed(nas, name).status == "HEALTHY"


@pytest.mark.parametrize("fs, profile, n", KINDS, ids=IDS)
def test_after_a_restart_the_pool_is_missing_until_kiboto_brings_it_back(nas, drives, fs, profile, n):
    name, mount = _make(nas, drives, fs, profile, n)
    # what a restart leaves: nothing mounted (btrfs, ext4), or the pool not imported (ZFS without its cache)
    sh("zpool", "export", name) if fs == "zfs" else sh("umount", mount)
    pool = _listed(nas, name)
    assert pool.status == "MISSING" and pool.total_bytes == 0
    assert [(x["kind"], x["subject"]) for x in pool_alerts.problems(nas.list_pools()) if x["subject"] == name] == [
        ("pool_missing", name)
    ]
    if fs != "zfs":  # nothing lands on the system disk while the pool is away
        with pytest.raises(OSError):
            pathlib.Path(mount, "stray.txt").write_text("x")
    assert pool_registry.bring_back_all(nas._run_cmd) == {name: ""}
    assert _listed(nas, name).status == "HEALTHY"
    assert pathlib.Path(mount, "kept.txt").read_text() == "still here"
    pathlib.Path(mount, "after.txt").write_text("writable again")


def test_a_btrfs_mirror_that_lost_a_drive_stays_readable(nas, drives):
    name, mount = _make(nas, drives, "btrfs", "raid1", 2)
    sh("umount", mount)
    sh("wipefs", "-a", drives[1])
    sh("udevadm", "settle", check=False)
    assert pool_registry.bring_back_all(nas._run_cmd) == {name: ""}
    assert pathlib.Path(mount, "kept.txt").read_text() == "still here"
    with pytest.raises(OSError):
        pathlib.Path(mount, "new.txt").write_text("x")  # read-only until the drive is replaced
    assert _listed(nas, name).status == "DEGRADED"
    assert ("pool_degraded", name) in [(x["kind"], x["subject"]) for x in pool_alerts.problems(nas.list_pools())]


def test_a_zfs_mirror_that_lost_a_drive_is_degraded_and_still_writable(nas, drives):
    name, mount = _make(nas, drives, "zfs", "mirror", 2)
    vdevs = [
        line.split()[0] for line in sh("zpool", "status", "-P", name).splitlines() if line.strip().startswith("/dev/")
    ]
    sh("zpool", "offline", name, vdevs[1])  # by the name the pool itself uses for the drive
    assert _listed(nas, name).status == "DEGRADED"
    pathlib.Path(mount, "new.txt").write_text("a mirror still takes writes on one drive")
    assert ("pool_degraded", name) in [(x["kind"], x["subject"]) for x in pool_alerts.problems(nas.list_pools())]


def test_a_pool_whose_only_drive_is_gone_is_missing_and_says_why(nas, drives):
    name, mount = _make(nas, drives, "ext4", "single", 1)
    sh("umount", mount)
    sh("wipefs", "-a", drives[0])
    sh("udevadm", "settle", check=False)
    why = pool_registry.bring_back_all(nas._run_cmd)[name]
    assert why and _listed(nas, name).status == "MISSING"
    with pytest.raises(OSError):
        pathlib.Path(mount, "stray.txt").write_text("x")


def test_a_zfs_pool_from_elsewhere_is_only_read_until_changes_are_allowed(nas, drives):
    name, mount = _make(nas, drives, "zfs", "mirror", 2)
    sh("zpool", "export", name)
    pool_registry.forget(name)  # as on a system that has never seen it
    found = next(p for p in nas.discover_external_pools() if p["pool_id"] == name)
    assert nas.import_pool(name, fs_type="zfs", guid=found["numeric_id"])["read_only"] is True
    pool = _listed(nas, name)
    assert pool.read_only is True and pool.status == "HEALTHY"
    assert pathlib.Path(mount, "kept.txt").read_text() == "still here"
    with pytest.raises(OSError):
        pathlib.Path(mount, "new.txt").write_text("x")
    assert pool_registry.find(name) is None  # not one of this system's pools yet
    assert nas.allow_changes(name)["status"] == "writable"
    pathlib.Path(mount, "new.txt").write_text("now it can change")
    assert _listed(nas, name).read_only is False
    assert pool_registry.find(name)["origin"] == "imported"
