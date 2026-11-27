"""Adding a drive to a pool from the app: each kind of pool grows with its own tool, onto empty drives only."""

import json
from types import SimpleNamespace

import pytest

from backend.hardware.pal import pool_grow as pg

GIB8 = 8 * 1024**3
D1 = "/dev/disk/by-id/virtio-KBTESTDISK1"


def zstatus(body: str, extra: str = "") -> str:
    return f"  pool: tank\n state: ONLINE\n{extra}config:\n\n\tNAME  STATE  READ WRITE CKSUM\n{body}\nerrors: No known data errors\n"


LONE = zstatus(f"\ttank  ONLINE  0 0 0\n\t  {D1}-part1  ONLINE  0 0 0\n")
MIRRORS = zstatus(
    f"\ttank  ONLINE  0 0 0\n\t  mirror-0  ONLINE  0 0 0\n\t    {D1}-part1  ONLINE  0 0 0\n"
    "\t    /dev/disk/by-id/virtio-KBTESTDISK2-part1  ONLINE  0 0 0\n"
)
RAIDZ = zstatus(
    f"\ttank  ONLINE  0 0 0\n\t  raidz1-0  ONLINE  0 0 0\n\t    {D1}-part1  ONLINE  0 0 0\n"
    "\t    /dev/disk/by-id/virtio-KBTESTDISK2-part1  ONLINE  0 0 0\n\t    /dev/disk/by-id/virtio-KBTESTDISK3-part1  ONLINE  0 0 0\n"
)
DEGRADED = MIRRORS.replace("KBTESTDISK2-part1  ONLINE", "KBTESTDISK2-part1  FAULTED")
LSBLK = {
    "blockdevices": [
        {"name": "vda", "path": "/dev/vda", "size": 24 * 1024**3, "type": "disk", "children": [{"name": "vda1"}]},
        {"name": "vdf", "path": "/dev/vdf", "size": GIB8, "type": "disk", "serial": "KBTESTDISK6"},
        {"name": "vdg", "path": "/dev/vdg", "size": GIB8, "type": "disk", "serial": "KBTESTDISK7"},
        {"name": "vdh", "path": "/dev/vdh", "size": GIB8 // 2, "type": "disk"},
    ]
}
ONE_BTRFS = "Label: 'media'\n\tdevid    1 size 8589934592 used 1 path /dev/vdd\n"
TWO_BTRFS = ONE_BTRFS + "\tdevid    2 size 8589934592 used 1 path /dev/vdc\n"


class Machine:
    def __init__(self, zpool=LONE, show=ONE_BTRFS, df="Data, single: total=1, used=1\n", balance="No balance found"):
        self.zpool, self.show, self.df, self.balance, self.seen = zpool, show, df, balance, []
        self.feature, self.refuse, self.refuse_balance = "enabled", False, False

    def __call__(self, cmd):
        self.seen.append(cmd)
        if cmd[:2] == ["lsblk", "-J"]:
            if "-d" in cmd:
                return 0, json.dumps({"blockdevices": [{"path": D1, "size": GIB8}]}), ""
            return 0, json.dumps(LSBLK), ""
        if cmd[:2] == ["zpool", "status"]:
            return 0, self.zpool, ""
        if cmd[:2] == ["zpool", "get"]:
            return 0, self.feature + "\n", ""
        if cmd[:3] == ["btrfs", "filesystem", "show"]:
            return 0, self.show, ""
        if cmd[:3] == ["btrfs", "filesystem", "df"]:
            return 0, self.df, ""
        if cmd[:3] == ["btrfs", "balance", "status"]:
            return 0, self.balance, ""
        if cmd[:3] == ["btrfs", "replace", "status"]:
            return 0, "Never started", ""
        if self.refuse and cmd[1:2] in (["attach"], ["add"], ["device"]):
            return 1, "", "cannot attach: no such device in pool"
        if self.refuse_balance and cmd[1:2] == ["balance"]:
            return 1, "", "ERROR: error during balancing"
        return 0, "", ""


def zfs(read_only=False):
    return SimpleNamespace(id="tank", fs_type="zfs", mountpoint="/mnt/storage/tank", read_only=read_only)


def btrfs():
    return SimpleNamespace(id="media", fs_type="btrfs", mountpoint="/mnt/storage/media", read_only=False)


def test_a_zfs_drive_on_its_own_can_become_a_mirror():
    p = pg.plan(zfs(), Machine())
    assert p["ways"] == [{"way": "mirror", "to": f"{D1}-part1", "label": f"{D1}-part1", "count": 1, "min": GIB8}]
    assert [d["path"] for d in p["drives"]] == ["/dev/vdh", "/dev/vdf", "/dev/vdg"]  # empty drives, by size


def test_making_a_mirror_attaches_the_drive_by_its_lasting_name(monkeypatch):
    monkeypatch.setattr(pg.dr, "by_id", lambda path: "/dev/disk/by-id/virtio-KBTESTDISK6")
    m = Machine()
    got = pg.start(zfs(), "mirror", f"{D1}-part1", ["/dev/vdf"], m)
    assert m.seen[-1] == ["zpool", "attach", "tank", f"{D1}-part1", "/dev/disk/by-id/virtio-KBTESTDISK6"]
    assert got == {
        "started": True,
        "pool": "tank",
        "way": "mirror",
        "added": ["/dev/disk/by-id/virtio-KBTESTDISK6"],
        "profile": "",
    }


def test_mirrors_take_one_more_mirror_of_two_drives():
    m = Machine(zpool=MIRRORS)
    p = pg.plan(zfs(), m)
    assert [w["way"] for w in p["ways"]] == ["add_mirror"] and p["ways"][0]["count"] == 2
    pg.start(zfs(), "add_mirror", "", ["/dev/vdf", "/dev/vdg"], m)
    assert m.seen[-1] == ["zpool", "add", "tank", "mirror", "/dev/vdf", "/dev/vdg"]  # no -f: ZFS checks the kind


def test_a_raidz_group_is_widened_only_where_zfs_can():
    m = Machine(zpool=RAIDZ)
    assert [(w["way"], w["to"]) for w in pg.plan(zfs(), m)["ways"]] == [("widen", "raidz1-0")]
    pg.start(zfs(), "widen", "raidz1-0", ["/dev/vdg"], m)
    assert m.seen[-1] == ["zpool", "attach", "tank", "raidz1-0", "/dev/vdg"]
    m.feature = "disabled"
    assert pg.plan(zfs(), m)["why"] == "cannot_grow"


def test_a_pool_with_a_broken_drive_is_mended_first():
    p = pg.plan(zfs(), Machine(zpool=DEGRADED))
    assert p["ways"] == [] and p["why"] == "not_healthy"


def test_while_it_copies_nothing_else_is_added():
    resilver = zstatus(
        f"\ttank  ONLINE  0 0 0\n\t  {D1}-part1  ONLINE  0 0 0\n",
        "  scan: resilver in progress since x\n\t1G done, 42.5% done\n",
    )
    p = pg.plan(zfs(), Machine(zpool=resilver))
    assert p["progress"] == {"running": True, "percent": 42.5} and p["ways"] == []
    with pytest.raises(pg.GrowError) as e:
        pg.start(zfs(), "mirror", f"{D1}-part1", ["/dev/vdf"], Machine(zpool=resilver))
    assert e.value.key == "busy"


def test_a_raidz_expansion_shows_its_progress():
    said = "expand: expansion of raidz1-0 in progress since Thu\n\t1G / 3G copied at 1M/s, 33.30% done, 0:30 to go\n"
    assert pg.zfs_progress(said) == {"running": True, "percent": 33.3}
    assert pg.zfs_progress("expand: expansion of raidz1-0 in progress since Thu\n") == {
        "running": True,
        "percent": None,
    }
    assert pg.zfs_progress("scan: scrub repaired 0B") == {"running": False, "percent": None}


@pytest.mark.parametrize(
    ("way", "to", "drives", "key"),
    [
        ("mirror", f"{D1}-part1", ["/dev/vdh"], "too_small"),
        ("mirror", f"{D1}-part1", ["/dev/vda"], "not_free"),
        ("mirror", f"{D1}-part1", ["/dev/vdf", "/dev/vdg"], "count"),
        ("mirror", "/dev/disk/by-id/someone-else", ["/dev/vdf"], "cannot_grow"),
        ("add_mirror", "", ["/dev/vdf", "/dev/vdf"], "cannot_grow"),
    ],
)
def test_what_does_not_fit_is_refused_with_a_reason(way, to, drives, key):
    m = Machine()
    with pytest.raises(pg.GrowError) as e:
        pg.start(zfs(), way, to, drives, m)
    assert e.value.key in (key, "no_way")
    assert not any(c[1:2] in (["attach"], ["add"]) for c in m.seen)


def test_the_same_drive_twice_and_a_read_only_pool_are_refused():
    m = Machine(zpool=MIRRORS)
    with pytest.raises(pg.GrowError) as e:
        pg.start(zfs(), "add_mirror", "", ["/dev/vdf", "/dev/vdf"], m)
    assert e.value.key == "count"
    with pytest.raises(pg.GrowError) as e:
        pg.start(zfs(read_only=True), "mirror", f"{D1}-part1", ["/dev/vdf"], Machine())
    assert e.value.key == "read_only"


def test_the_pools_own_refusal_is_said():
    m = Machine()
    m.refuse = True
    with pytest.raises(pg.GrowError, match="no such device in pool"):
        pg.start(zfs(), "mirror", f"{D1}-part1", ["/dev/vdf"], m)


def test_a_btrfs_drive_on_its_own_becomes_a_mirror_with_a_conversion():
    m = Machine()
    p = pg.plan(btrfs(), m)
    assert [w["way"] for w in p["ways"]] == ["mirror", "add"]
    got = pg.start(btrfs(), "mirror", "", ["/dev/vdf"], m)
    assert m.seen[-2] == ["btrfs", "device", "add", "/dev/vdf", "/mnt/storage/media"]
    assert m.seen[-1] == [
        "btrfs",
        "balance",
        "start",
        "--bg",
        "-dconvert=raid1",
        "-mconvert=raid1",
        "/mnt/storage/media",
    ]
    assert got["profile"] == "raid1"


def test_more_space_on_btrfs_spreads_copies_but_not_single_files():
    m = Machine(show=TWO_BTRFS, df="Data, RAID1: total=1, used=1\n")
    assert [w["way"] for w in pg.plan(btrfs(), m)["ways"]] == ["add"]
    assert pg.start(btrfs(), "add", "", ["/dev/vdg"], m)["profile"] == "raid1"
    assert m.seen[-1] == ["btrfs", "balance", "start", "--bg", "--full-balance", "/mnt/storage/media"]
    single = Machine(show=TWO_BTRFS)
    assert pg.start(btrfs(), "add", "", ["/dev/vdg"], single)["profile"] == "single"
    assert single.seen[-1][:3] == ["btrfs", "device", "add"]


def test_a_balance_that_does_not_start_is_said_after_the_drive_was_added():
    m = Machine()
    m.refuse_balance = True
    with pytest.raises(pg.GrowError) as e:
        pg.start(btrfs(), "mirror", "", ["/dev/vdf"], m)
    assert e.value.key == "balance_failed" and "was added" in str(e.value)


def test_a_btrfs_balance_shows_its_progress_and_blocks_the_next():
    m = Machine(balance="Balance on '/mnt/storage/media' is running\n2 out of about 10 chunks balanced, 80% left\n")
    p = pg.plan(btrfs(), m)
    assert p["progress"] == {"running": True, "percent": 20.0} and p["ways"] == []
    assert pg.btrfs_progress("Balance on '/x' is paused\n") == {"running": True, "percent": None}


def test_a_btrfs_pool_missing_a_drive_or_unreadable_cannot_grow():
    missing = Machine(show=ONE_BTRFS + "\tdevid    2 size 0 used 0 path  MISSING\n")
    assert pg.plan(btrfs(), missing)["why"] == "not_healthy"
    broken = Machine()
    broken.show = None
    broken.__class__ = type("Broken", (Machine,), {"__call__": lambda self, cmd: (1, "", "no")})
    assert pg.plan(btrfs(), broken)["why"] == "no_status"
    assert pg.plan(zfs(), broken)["why"] == "no_status"


def test_ext4_and_other_kinds_cannot_grow():
    pool = SimpleNamespace(id="docs", fs_type="ext4", mountpoint="/mnt/storage/docs", read_only=False)
    assert pg.plan(pool, Machine())["why"] == "cannot_grow"


def test_the_adapter_answers_a_refusal_and_records_the_new_drives(monkeypatch, tmp_path):
    from backend.hardware.pal import generic_linux, pool_registry
    from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter

    monkeypatch.setattr(pool_registry, "_file", lambda: str(tmp_path / "pools.json"))
    pool_registry.record("media", "btrfs", "single", "u-1", ["/dev/disk/by-id/a"], "/mnt/storage/media")
    a = GenericLinuxStorageAdapter.__new__(GenericLinuxStorageAdapter)
    monkeypatch.setattr(a, "resolve_pool", lambda pid: btrfs())
    monkeypatch.setattr(a, "_run_cmd", Machine())
    assert a._grow_plan_here("media")["ways"]
    assert a._grow_pool_here("media", "mirror", "", ["/dev/vdh"])["why"] == "too_small"
    monkeypatch.setattr(generic_linux, "_through_door", lambda op, here, **kw: here(**kw))
    monkeypatch.setattr(pg.dr, "by_id", lambda path: "/dev/disk/by-id/b")
    assert a.grow_pool("media", "mirror", "", ["/dev/vdf"])["started"] is True
    row = pool_registry.find("media")
    assert row["members"] == ["/dev/disk/by-id/a", "/dev/disk/by-id/b"] and row["profile"] == "raid1"
    assert generic_linux.members_after_grow("nobody", ["/x"]) is None


def test_the_door_has_the_grow_operations():
    from backend.services import host_door

    assert host_door.OPERATIONS["storage.grow_plan"].args == {"pool_id": (str,)}
    assert host_door.OPERATIONS["storage.grow_pool"].args == {
        "pool_id": (str,),
        "way": (str,),
        "to": (str,),
        "drives": (list,),
    }


class _Adapter:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def grow_plan(self, pool_id):
        return {"pool": pool_id, "ways": []}

    def grow_pool(self, pool_id, way, to, drives):
        self.asked.append((pool_id, way, to, drives))
        return self.answer


@pytest.mark.real_confirmations
def test_adding_is_confirmed_first_then_started(client, auth_headers, monkeypatch):
    adapter = _Adapter({"started": True, "pool": "tank", "way": "mirror", "added": ["b"]})
    monkeypatch.setattr("backend.api.storage.get_storage_platform", lambda: adapter)
    assert client.get("/api/storage/pools/tank/grow", headers=auth_headers).json() == {"pool": "tank", "ways": []}
    body = {"way": "mirror", "to": "a", "drives": ["/dev/vdf"]}
    first = client.post("/api/storage/pools/tank/grow", json=body, headers=auth_headers)
    assert first.status_code == 428 and adapter.asked == []
    asked = first.json()
    assert asked["action"] == "storage.pool.grow"
    token = client.post(
        "/api/confirmations", headers=auth_headers, json={"action": asked["action"], "target": asked["target"]}
    ).json()["token"]
    done = client.post("/api/storage/pools/tank/grow", json=body, headers={**auth_headers, "X-Confirm-Token": token})
    assert done.status_code == 200 and adapter.asked == [("tank", "mirror", "a", ["/dev/vdf"])]


def test_a_refused_drive_is_a_conflict_with_its_reason(client, auth_headers, monkeypatch):
    adapter = _Adapter({"started": False, "why": "not_free", "message": "That drive is not an empty drive."})
    monkeypatch.setattr("backend.api.storage.get_storage_platform", lambda: adapter)
    res = client.post("/api/storage/pools/tank/grow", json={"way": "add", "drives": ["/dev/vdb"]}, headers=auth_headers)
    assert res.status_code == 409 and "not an empty drive" in res.json()["detail"]


def test_the_host_systems_own_pools_are_not_grown_here(client, auth_headers, monkeypatch):
    from backend.hardware.pal.base import PlatformCapabilityError

    class Host:
        def grow_plan(self, pool_id):
            raise PlatformCapabilityError("Add drives in the host system's own storage settings.")

        def grow_pool(self, pool_id, way, to, drives):
            raise LookupError("no such pool")

    monkeypatch.setattr("backend.api.storage.get_storage_platform", lambda: Host())
    assert client.get("/api/storage/pools/tank/grow", headers=auth_headers).status_code == 403
    res = client.post("/api/storage/pools/tank/grow", json={"way": "add", "drives": ["/dev/vdb"]}, headers=auth_headers)
    assert res.status_code == 404
