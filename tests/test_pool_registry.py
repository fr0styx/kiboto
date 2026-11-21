"""The record of the pools Kiboto made.

Found with real tools on a Debian machine: a btrfs or ext4 pool was not listed after Kiboto made it
(the listing went by drive names and sizes), nothing mounted it again after a restart, and a write
into its empty folder landed on the system disk. A pool is now written down when it is made or
imported, listed from that record, brought back at start, and shown as missing when it is away."""

import json
import os

import pytest

from backend.hardware.pal import pool_registry as reg
from backend.hardware.pal_storage import GenericLinuxStorageAdapter
from backend.services import pool_alerts


class Tools:
    """Pretend tools: `answers` maps the start of a command to (code, out, err); the rest succeed."""

    def __init__(self):
        self.ran = []
        self.answers = {}

    def __call__(self, cmd):
        self.ran.append(cmd)
        for start, answer in self.answers.items():
            if " ".join(cmd).startswith(start):
                return answer(cmd) if callable(answer) else answer
        return 0, "", ""

    def did(self, start):
        return [c for c in self.ran if " ".join(c).startswith(start)]


@pytest.fixture
def tools():
    return Tools()


def _row(tmp_path, name="media", fs="btrfs", profile="raid1", uuid="u-1", **more):
    mp = str(tmp_path / "pools" / name)
    return reg.record(name, fs, profile, uuid, [str(tmp_path / "drive-a")], mp, **more)


# ---- the record itself


def test_a_pool_is_written_down_found_renamed_and_forgotten(tmp_path):
    assert reg.load() == []
    _row(tmp_path, options="noatime")
    _row(tmp_path, name="tank", fs="zfs", profile="mirror", uuid="42")
    assert [r["name"] for r in reg.load()] == ["media", "tank"]
    assert reg.find("media")["options"] == "noatime" and reg.find("nope") is None
    _row(tmp_path, uuid="u-2")  # written again: in place of the older record
    assert [r["uuid"] for r in reg.load() if r["name"] == "media"] == ["u-2"]
    reg.set_ejected("media", True)
    reg.set_ejected("media", True)  # twice changes nothing
    assert reg.find("media")["ejected"] is True
    reg.rename("media", "films")
    assert reg.find("films") and not reg.find("media")
    assert reg.forget("films") is True and reg.forget("films") is False
    assert [r["name"] for r in reg.load()] == ["tank"]


def test_a_record_that_cannot_be_read_is_no_pools(tmp_path):
    path = reg._file()
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert reg.load() == []
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            [{"name": "ok", "fs_type": "ext4"}, {"name": "", "fs_type": "ext4"}, {"name": "x", "fs_type": "ntfs"}, 7], f
        )
    assert [r["name"] for r in reg.load()] == ["ok"]


def test_the_id_comes_from_the_file_system(tools):
    tools.answers["zpool get"] = (0, "123\n", "")
    tools.answers["blkid"] = (0, "abc-def\n", "")
    assert reg.read_uuid("zfs", "tank", "", tools) == "123"
    assert reg.read_uuid("ext4", "docs", "/dev/sdb", tools) == "abc-def"
    tools.answers["blkid"] = (2, "", "nothing")
    assert reg.read_uuid("btrfs", "docs", "/dev/sdb", tools) == ""


def test_there_means_this_very_pool(tmp_path, tools):
    row = _row(tmp_path)
    tools.answers["findmnt"] = (0, "u-1\n", "")
    assert reg.is_there(row, tools) is True
    tools.answers["findmnt"] = (0, "someone-else\n", "")  # another file system sits on its folder
    assert reg.is_there(row, tools) is False
    tools.answers["findmnt"] = (1, "", "")
    assert reg.is_there(row, tools) is False
    z = _row(tmp_path, name="tank", fs="zfs", uuid="42")
    tools.answers["zpool get"] = (0, "42\n", "")
    assert reg.is_there(z, tools) is True
    tools.answers["zpool get"] = (1, "", "no such pool")
    assert reg.is_there(z, tools) is False


def test_only_an_empty_unmounted_folder_is_made_unwritable(tmp_path, tools):
    empty, full = tmp_path / "empty", tmp_path / "full"
    empty.mkdir()
    full.mkdir()
    (full / "a.txt").write_text("x")
    reg.protect(str(empty), tools)
    reg.protect(str(full), tools)
    reg.protect(str(tmp_path / "not-there"), tools)
    assert tools.did("chattr") == [["chattr", "+i", str(empty)]]
    tools.answers["chattr +i"] = (1, "", "Operation not supported")
    reg.protect(str(empty), tools)  # a file system without the flag: left as it is
    reg.unprotect(str(empty), tools)
    reg.unprotect(str(tmp_path / "not-there"), tools)
    assert tools.did("chattr -i") == [["chattr", "-i", str(empty)]]


# ---- bringing a pool back


def test_a_pool_that_is_there_is_left_alone(tmp_path, tools):
    row = _row(tmp_path)
    tools.answers["findmnt"] = (0, "u-1\n", "")
    assert reg.bring_back(row, tools) == ""
    assert not tools.did("mount")


def test_btrfs_is_scanned_then_mounted_by_its_id(tmp_path, tools):
    row = _row(tmp_path, options="noatime")
    tools.answers["findmnt"] = (1, "", "")
    assert reg.bring_back(row, tools) == ""
    names = [c[0] + " " + c[1] for c in tools.ran]
    assert names.index("btrfs device") < names.index("mount -o")
    assert tools.did("mount") == [["mount", "-o", "noatime", "UUID=u-1", row["mountpoint"]]]
    assert tools.did("chattr +i")  # the new folder is closed before anything is mounted on it


def test_a_mirror_with_a_drive_gone_comes_up_read_only(tmp_path, tools):
    row = _row(tmp_path, options="noatime")
    tools.answers["findmnt"] = (1, "", "")
    tools.answers["mount -o noatime UUID"] = (32, "", "fsconfig() failed")
    assert reg.bring_back(row, tools) == ""
    assert tools.did("mount")[-1] == ["mount", "-o", "noatime,degraded,ro", "UUID=u-1", row["mountpoint"]]
    tools.answers["mount -o noatime,degraded,ro"] = (32, "", "still no")
    assert "fsconfig" in reg.bring_back(row, tools)


def test_a_pool_without_a_second_copy_is_not_forced(tmp_path, tools):
    row = _row(tmp_path, name="docs", fs="ext4", profile="single", uuid="e-1")
    tools.answers["findmnt"] = (1, "", "")
    tools.answers["mount"] = (32, "", "can't find UUID=e-1")
    assert "can't find" in reg.bring_back(row, tools)
    assert tools.did("mount") == [["mount", "UUID=e-1", row["mountpoint"]]]


def test_zfs_is_imported_by_its_id(tmp_path, tools):
    row = _row(tmp_path, name="tank", fs="zfs", profile="mirror", uuid="42")
    tools.answers["zpool get"] = (1, "", "no such pool")
    assert reg.bring_back(row, tools) == ""
    assert tools.did("zpool import") == [["zpool", "import", "42"]]
    tools.answers["zpool import"] = (1, "", "no pools available to import")
    assert "no pools available" in reg.bring_back(row, tools)


def test_what_cannot_be_found_says_why(tmp_path, tools):
    row = _row(tmp_path, uuid="")
    tools.answers["findmnt"] = (1, "", "")
    assert "no id" in reg.bring_back(row, tools)
    blocked = tmp_path / "a-file"
    blocked.write_text("x")
    row2 = reg.record("docs", "ext4", "single", "e-1", [], str(blocked / "docs"))
    assert reg.bring_back(row2, tools)  # its folder cannot be made


def test_start_brings_back_all_but_the_ejected(tmp_path, tools):
    _row(tmp_path)
    _row(tmp_path, name="docs", fs="ext4", profile="single", uuid="e-1")
    _row(tmp_path, name="away", fs="ext4", profile="single", uuid="e-2")
    reg.set_ejected("away", True)
    tools.answers["findmnt"] = (1, "", "")
    tools.answers["mount UUID=e-1"] = (32, "", "can't find UUID=e-1")
    done = reg.bring_back_all(tools)
    assert done == {"media": "", "docs": "can't find UUID=e-1"}


# ---- the adapter keeps the record and lists from it


@pytest.fixture
def nas(tmp_path, tools):
    adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path / "pools"))
    adapter._run_cmd = tools
    adapter._resolve_disk_path = lambda d: d
    adapter._discover_hal_disks = lambda: []
    return adapter


def _pool(adapter, name):
    return next((p for p in adapter.list_pools() if p.id == name), None)


def test_a_made_pool_is_written_down_and_listed(nas, tools, tmp_path):
    a, b = tmp_path / "drive-a", tmp_path / "drive-b"
    a.write_text("")
    b.write_text("")
    tools.answers["blkid -o value -s UUID"] = (0, "u-9\n", "")
    mp = str(tmp_path / "pools" / "media")
    nas.create_pool("media", "btrfs", "raid1", [str(a), str(b)], mp)
    row = reg.find("media")
    assert (row["uuid"], row["profile"], row["members"]) == ("u-9", "raid1", [str(a), str(b)])
    assert row["options"].startswith("compress=zstd")
    tools.answers["findmnt -rno UUID -M"] = (0, "u-9\n", "")
    tools.answers["btrfs filesystem show"] = (0, "Label: media  uuid: u-9\n devid 1\n devid 2\n", "")
    p = _pool(nas, "media")
    assert (p.status, p.fs_type, p.fs_profile, p.pool_type, p.parity_protected) == (
        "HEALTHY",
        "btrfs",
        "raid1",
        "btrfs_raid",
        True,
    )
    assert [m.status for m in p.members] == ["OK", "OK"] and p.total_bytes > 0
    tools.answers["btrfs filesystem show"] = (0, "Label: media\n devid 1\n *** Some devices missing\n", "")
    assert _pool(nas, "media").status == "DEGRADED"


def test_a_pool_that_is_not_there_is_missing_not_gone(nas, tools, tmp_path):
    reg.record("docs", "ext4", "single", "e-1", [str(tmp_path / "unplugged")], str(tmp_path / "pools" / "docs"))
    reg.record("tank", "zfs", "raidz1", "42", [], "/mnt/tank")
    tools.answers["findmnt -rno UUID -M"] = (1, "", "")
    tools.answers["zpool list"] = (0, "", "")
    docs, tank = _pool(nas, "docs"), _pool(nas, "tank")
    assert (docs.status, docs.total_bytes, [m.status for m in docs.members]) == ("MISSING", 0, ["MISSING"])
    assert (tank.status, tank.pool_type, tank.parity_protected) == ("MISSING", "zfs_raid", True)
    with pytest.raises(RuntimeError, match="was not found"):
        nas.trigger_scrub("docs")
    kinds = [(x["kind"], x["subject"]) for x in pool_alerts.problems(nas.list_pools())]
    assert ("pool_missing", "docs") in kinds and ("pool_missing", "tank") in kinds
    assert not [k for k in kinds if k[0].startswith("disk_")]  # one alert for the pool, none per drive


def test_an_ejected_pool_is_away_on_purpose_and_can_be_found_again(nas, tools, tmp_path):
    mp = tmp_path / "pools" / "docs"
    mp.mkdir(parents=True)
    reg.record("docs", "ext4", "single", "e-1", [], str(mp))
    tools.answers["findmnt -rno UUID -M"] = (0, "e-1\n", "")
    tools.answers["fuser"] = (1, "", "")
    assert nas.export_pool("docs")["status"] == "exported"
    assert reg.find("docs")["ejected"] is True and _pool(nas, "docs") is None
    tools.answers["zpool import"] = (1, "", "")
    assert {
        "pool_id": "docs",
        "fs_type": "ext4",
        "status": "EJECTED",
        "detachable": True,
    } in nas.discover_external_pools()
    tools.answers["blkid -U"] = (2, "", "")  # its drive is not connected: nothing to find
    assert nas.discover_external_pools() == []
    tools.answers["findmnt -rno UUID -M"] = (1, "", "")
    res = nas.import_pool("docs", fs_type="ext4")
    assert res["status"] == "imported" and res["mountpoint"] == str(mp)
    assert tools.did("mount UUID=e-1") and reg.find("docs")["ejected"] is False
    tools.answers["mount"] = (32, "", "can't find UUID=e-1")
    with pytest.raises(RuntimeError, match="docs could not be mounted: can't find"):
        nas.import_pool("docs", fs_type="ext4")


def test_an_imported_pool_is_written_down(nas, tools, tmp_path):
    tools.answers["zpool get"] = (0, "77\n", "")
    tools.answers["zfs get"] = (0, "/mnt/tank\n", "")
    nas.import_pool("tank", fs_type="zfs")
    row = reg.find("tank")
    assert (row["uuid"], row["mountpoint"], row["origin"]) == ("77", "/mnt/tank", "imported")
    reg.set_ejected("tank", True)
    nas.import_pool("tank", fs_type="zfs")  # known already: only no longer away
    assert reg.find("tank")["ejected"] is False
    tools.answers["findmnt -rno UUID -M"] = (0, "b-5\n", "")
    tools.answers["findmnt -rno SOURCE -M"] = (0, "/dev/sdq1\n", "")
    res = nas.import_pool("backup", fs_type="btrfs", target_mount=str(tmp_path / "pools" / "backup"))
    assert res["status"] == "imported"
    row = reg.find("backup")
    assert (row["uuid"], row["members"], row["origin"]) == ("b-5", ["/dev/sdq1"], "imported")


def test_disconnect_erase_and_rename_keep_the_record_true(nas, tools, tmp_path, monkeypatch):
    mp = tmp_path / "pools" / "docs"
    mp.mkdir(parents=True)
    reg.record("docs", "ext4", "single", "e-1", [], str(mp))
    reg.record("media", "btrfs", "single", "u-1", [], str(tmp_path / "pools" / "media"))
    tools.answers["findmnt -rno UUID -M"] = lambda cmd: (0, "e-1\n" if cmd[-1].endswith("docs") else "u-1\n", "")
    assert nas.destroy_pool("docs")["status"] == "disconnected"
    assert reg.find("docs")["ejected"] is True
    res = nas.rename_pool("media", "films")
    assert res["status"] == "renamed" and reg.find("films") and not reg.find("media")

    from backend.hardware.pal import pool_erase

    monkeypatch.setattr(
        pool_erase, "plan", lambda pool, run: {"pool": pool.id, "mountpoint": str(mp), "drives": ["/dev/sdz"]}
    )
    monkeypatch.setattr(pool_erase, "execute", lambda plan, run: plan["drives"])
    reg.set_ejected("docs", False)
    assert nas.erase_pool("docs")["status"] == "erased"
    assert reg.find("docs") is None and not mp.exists()


def test_start_up_step(monkeypatch, tools, tmp_path):
    from backend import main

    seen = []
    monkeypatch.setattr(reg, "bring_back_all", lambda run: seen.append(run) or {})
    main._bring_pools_back()
    assert seen == []  # no recorded pools: the storage platform is not even asked
    _row(tmp_path)
    adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path / "pools"))
    adapter._run_cmd = tools
    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda: adapter)
    main._bring_pools_back()
    assert seen == [tools]

    def broken():
        raise RuntimeError("no platform")

    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", broken)
    main._bring_pools_back()  # logged, and the start goes on
