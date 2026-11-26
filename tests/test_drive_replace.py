"""Replacing a drive of a pool from the app: the pool's own tool rebuilds onto an empty drive."""

import json
from types import SimpleNamespace

import pytest

from backend.hardware.pal import drive_replace as dr

MIRROR = """  pool: tank
 state: DEGRADED
config:

\tNAME                                          STATE     READ WRITE CKSUM
\ttank                                          DEGRADED     0     0     0
\t  mirror-0                                    DEGRADED     0     0     0
\t    /dev/disk/by-id/virtio-KBTESTDISK1-part1  ONLINE       0     0     0
\t    1234567890123                             UNAVAIL      0     0     0  was /dev/disk/by-id/virtio-KBTESTDISK2-part1
\tcache
\t  /dev/nvme0n1                                ONLINE       0     0     0

errors: No known data errors
"""
STRIPE = """config:

\tNAME                                        STATE     READ WRITE CKSUM
\tfast                                        ONLINE       0     0     0
\t  /dev/disk/by-id/virtio-KBTESTDISK3-part1  ONLINE       0     0     0
\t  /dev/disk/by-id/virtio-KBTESTDISK4-part1  ONLINE       0     0     0
"""
GIB8 = 8 * 1024**3
LSBLK = {
    "blockdevices": [
        {"name": "vda", "path": "/dev/vda", "size": 24 * 1024**3, "type": "disk", "children": [{"name": "vda1"}]},
        {
            "name": "vdb",
            "path": "/dev/vdb",
            "size": GIB8,
            "type": "disk",
            "fstype": None,
            "children": [{"name": "vdb1"}],
        },
        {"name": "vdf", "path": "/dev/vdf", "size": GIB8, "type": "disk", "fstype": "ext4", "mountpoint": "/mnt/x"},
        {"name": "vdg", "path": "/dev/vdg", "size": GIB8, "type": "disk", "serial": "KBTESTDISK6", "rota": False},
        {"name": "vdh", "path": "/dev/vdh", "size": GIB8 // 2, "type": "disk"},
        {"name": "sr0", "path": "/dev/sr0", "size": GIB8, "type": "rom"},
        {"name": "vdi", "path": "/dev/vdi", "size": GIB8, "type": "disk", "ro": True},
    ]
}


class Machine:
    def __init__(self, zpool=MIRROR, show="", df="Data, RAID1: total=1, used=1\n", replace_status="Never started"):
        self.zpool, self.show, self.df, self.replace_status, self.seen = zpool, show, df, replace_status, []
        self.refuse = False

    def __call__(self, cmd):
        self.seen.append(cmd)
        if cmd[:2] == ["lsblk", "-J"]:
            if "-d" in cmd:
                # the size the mirror's drive has, by the name the pool knows it by
                return (
                    0,
                    json.dumps({"blockdevices": [{"path": "/dev/disk/by-id/virtio-KBTESTDISK1", "size": GIB8}]}),
                    "",
                )
            return 0, json.dumps(LSBLK), ""
        if cmd[:2] == ["zpool", "status"]:
            return 0, self.zpool, ""
        if cmd[:3] == ["btrfs", "filesystem", "show"]:
            return 0, self.show, ""
        if cmd[:3] == ["btrfs", "filesystem", "df"]:
            return 0, self.df, ""
        if cmd[:3] == ["btrfs", "replace", "status"]:
            return 0, self.replace_status, ""
        if cmd[1:2] == ["replace"] and self.refuse:
            return 1, "", "cannot replace: device is too small"
        return 0, "", ""


ZFS_POOL = SimpleNamespace(id="tank", fs_type="zfs", mountpoint="/mnt/storage/tank")
BTRFS_POOL = SimpleNamespace(id="vdd", fs_type="btrfs", mountpoint="/mnt/storage/media")


def test_only_empty_whole_drives_large_enough_are_offered():
    drives = dr.free_drives(Machine(), at_least=GIB8)
    assert [d["path"] for d in drives] == ["/dev/vdg"]  # not the system disk, a used one, a small one, a CD
    assert drives[0]["serial"] == "KBTESTDISK6" and drives[0]["rotational"] is False
    assert [d["dev"] for d in dr.free_drives(Machine())] == ["vdh", "vdg"]  # smallest first


def test_a_zfs_mirror_with_a_missing_drive_can_rebuild_it():
    leaves, copies = dr.zfs_leaves(MIRROR)
    assert copies is True and [x["section"] for x in leaves] == ["data", "data", "cache"]
    assert leaves[1] == {
        "name": "1234567890123",
        "state": "UNAVAIL",
        "group": "mirror-0",
        "section": "data",
        "was": "/dev/disk/by-id/virtio-KBTESTDISK2-part1",
    }
    p = dr.plan(ZFS_POOL, Machine())
    assert p["can"] is True and [m["state"] for m in p["members"]] == ["ONLINE", "UNAVAIL"]
    assert p["members"][1]["label"].endswith("KBTESTDISK2-part1")  # named by the drive it was
    assert [d["path"] for d in p["drives"]] == ["/dev/vdg"]  # the half-size drive is not offered


def test_a_pool_without_copies_cannot_rebuild():
    assert dr.zfs_leaves(STRIPE)[1] is False
    assert dr.plan(ZFS_POOL, Machine(zpool=STRIPE))["why"] == "no_copy"
    assert dr.plan(SimpleNamespace(id="vdf", fs_type="ext4", mountpoint="/m"), Machine())["why"] == "one_drive"
    single = Machine(show="devid 1 size 8 used 1 path /dev/vdd\n", df="Data, single: total=1\n")
    assert dr.plan(BTRFS_POOL, single)["why"] == "no_copy"


def test_btrfs_names_its_devices_and_a_missing_one():
    show = "Label: 'media'\n\tdevid    1 size 8589934592 used 1 path /dev/vdd\n\tdevid    2 size 8589934592 used 1 path /dev/vde MISSING\n"
    devices = dr.btrfs_devices(show)
    assert devices[1] == {"devid": 2, "size_bytes": GIB8, "path": "", "missing": True}
    p = dr.plan(BTRFS_POOL, Machine(show=show))
    assert p["can"] is True and p["members"][1]["state"] == "MISSING" and p["members"][1]["id"] == "2"
    assert dr.btrfs_profile("Data, RAID10: total=1\n") == "raid10"


def test_the_rebuild_starts_with_the_pools_own_tool(monkeypatch):
    monkeypatch.setattr(dr, "by_id", lambda path: "/dev/disk/by-id/virtio-KBTESTDISK6")
    m = Machine()
    done = dr.start(ZFS_POOL, "1234567890123", "/dev/vdg", m)
    assert m.seen[-1] == ["zpool", "replace", "tank", "1234567890123", "/dev/disk/by-id/virtio-KBTESTDISK6"]
    assert done["started"] is True and done["old"].endswith("KBTESTDISK2-part1")
    show = "\tdevid    1 size 8589934592 used 1 path /dev/vdd\n\tdevid    2 size 8589934592 used 1 path /dev/vde\n"
    b = Machine(show=show)
    dr.start(BTRFS_POOL, "2", "/dev/vdg", b)
    assert b.seen[-1] == [
        "btrfs",
        "replace",
        "start",
        "-f",
        "2",
        "/dev/disk/by-id/virtio-KBTESTDISK6",
        "/mnt/storage/media",
    ]


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [("/dev/disk/by-id/someone-else", "/dev/vdg", "no_member"), ("1234567890123", "/dev/vdb", "not_free")],
)
def test_a_wrong_drive_is_refused_before_anything_runs(old, new, key):
    m = Machine()
    with pytest.raises(dr.ReplaceError) as e:
        dr.start(ZFS_POOL, old, new, m)
    assert e.value.key == key and not [c for c in m.seen if c[1:2] == ["replace"]]


def test_a_running_rebuild_or_a_refusal_is_said(monkeypatch):
    monkeypatch.setattr(dr, "by_id", lambda path: path)
    busy = Machine(zpool=MIRROR.replace("config:", "  scan: resilver in progress since Thu\n\t25.47% done\nconfig:"))
    assert dr.plan(ZFS_POOL, busy)["progress"] == {"running": True, "percent": 25.47}
    with pytest.raises(dr.ReplaceError) as e:
        dr.start(ZFS_POOL, "1234567890123", "/dev/vdg", busy)
    assert e.value.key == "busy"
    m = Machine()
    m.refuse = True
    with pytest.raises(dr.ReplaceError) as e:
        dr.start(ZFS_POOL, "1234567890123", "/dev/vdg", m)
    assert e.value.key == "failed" and "too small" in str(e.value)
    assert dr.btrfs_progress("12.5% done, 0 write errs, 0 uncorr. read errs") == {"running": True, "percent": 12.5}
    assert dr.btrfs_progress("Started on 26.Nov, finished on 26.Nov, 0 write errs")["running"] is False


def test_a_drive_is_named_by_its_lasting_name(tmp_path):
    (tmp_path / "dev").mkdir()
    disk = tmp_path / "dev" / "vdg"
    disk.write_text("")
    ids = tmp_path / "by-id"
    ids.mkdir()
    (ids / "virtio-KBTESTDISK6").symlink_to(disk)
    (ids / "virtio-KBTESTDISK6-part1").symlink_to(tmp_path / "dev" / "vdg1")
    (ids / "wwn-0x5000c5").symlink_to(disk)
    assert dr.by_id(str(disk), str(ids)) == str(ids / "wwn-0x5000c5")
    assert dr.by_id(str(tmp_path / "dev" / "other"), str(ids)) == str(tmp_path / "dev" / "other")
    assert dr.by_id(str(disk), str(tmp_path / "nowhere")) == str(disk)


# --- the adapter, the door and the page's routes


def test_the_adapter_answers_a_refusal_instead_of_raising(monkeypatch):
    from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter

    a = GenericLinuxStorageAdapter.__new__(GenericLinuxStorageAdapter)
    pool = SimpleNamespace(id="tank", fs_type="zfs", mountpoint="/m", read_only=False)
    monkeypatch.setattr(a, "resolve_pool", lambda pid: pool)
    monkeypatch.setattr(a, "_run_cmd", Machine())
    got = a._replace_drive_here("tank", "/dev/disk/by-id/nobody", "/dev/vdg")
    assert got == {"started": False, "why": "no_member", "message": "That drive is not one of this pool's drives."}
    assert a._replace_plan_here("tank")["can"] is True
    pool.read_only = True
    assert a._replace_drive_here("tank", "1234567890123", "/dev/vdg")["why"] == "read_only"


def test_the_door_has_the_replace_operations():
    from backend.services import host_door

    assert host_door.OPERATIONS["storage.replace_plan"].args == {"pool_id": (str,)}
    assert host_door.OPERATIONS["storage.replace_drive"].args == {"pool_id": (str,), "old": (str,), "new": (str,)}


class _Adapter:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def replace_plan(self, pool_id):
        return {"pool": pool_id, "can": True}

    def replace_drive(self, pool_id, old, new):
        self.asked.append((pool_id, old, new))
        return self.answer


@pytest.mark.real_confirmations
def test_replacing_is_confirmed_first_then_started(client, auth_headers, monkeypatch):
    adapter = _Adapter({"started": True, "pool": "tank", "old": "a", "new": "b"})
    monkeypatch.setattr("backend.api.storage.get_storage_platform", lambda: adapter)
    plan = client.get("/api/storage/pools/tank/replace", headers=auth_headers).json()
    assert plan.pop("edition") in ("yes", "check", "host") and plan == {"pool": "tank", "can": True}
    body = {"old": "1234567890123", "new": "/dev/vdg"}
    first = client.post("/api/storage/pools/tank/replace", json=body, headers=auth_headers)
    assert first.status_code == 428 and adapter.asked == []
    asked = first.json()
    assert asked["action"] == "storage.drive.replace"
    token = client.post(
        "/api/confirmations", headers=auth_headers, json={"action": asked["action"], "target": asked["target"]}
    ).json()["token"]
    done = client.post("/api/storage/pools/tank/replace", json=body, headers={**auth_headers, "X-Confirm-Token": token})
    assert done.status_code == 200 and adapter.asked == [("tank", "1234567890123", "/dev/vdg")]


def test_a_refused_replacement_is_a_conflict_with_its_reason(client, auth_headers, monkeypatch):
    adapter = _Adapter({"started": False, "why": "not_free", "message": "That drive is not an empty drive."})
    monkeypatch.setattr("backend.api.storage.get_storage_platform", lambda: adapter)
    res = client.post("/api/storage/pools/tank/replace", json={"old": "x", "new": "/dev/vdb"}, headers=auth_headers)
    assert res.status_code == 409 and "not an empty drive" in res.json()["detail"]
