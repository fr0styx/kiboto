"""Snapshots on a machine whose pools sit inside the main storage folder: each share's snapshots are
taken, listed, deleted and restored in its own pool (btrfs needs the same file system)."""

import os
from types import SimpleNamespace

import pytest

from backend.hardware.pal import base as pal_base
from backend.hardware.pal import generic_linux as gl
from backend.hardware.pal import pool_registry
from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter
from backend.services import snapshot_service


@pytest.fixture
def box(tmp_path, monkeypatch):
    main = tmp_path / "storage"
    pools = {"docs": "ext4", "media": "btrfs", "tank": "zfs"}
    rows = []
    for name, fs in pools.items():
        (main / name).mkdir(parents=True)
        rows.append({"name": name, "fs_type": fs, "mountpoint": str(main / name), "ejected": False})
    (main / "docs" / "films").mkdir()
    (main / "media" / "music").mkdir()
    (main / "tank" / "photos").mkdir()
    monkeypatch.setattr(pool_registry, "load", lambda: [dict(r) for r in rows])
    monkeypatch.setattr(pool_registry, "find", lambda n: next((dict(r) for r in rows if r["name"] == n), None))

    def fs_of(path):
        real = os.path.realpath(path)
        for name, fs in pools.items():
            if real == str(main / name) or real.startswith(str(main / name) + "/"):
                return fs
        return "ext4"

    monkeypatch.setattr(gl, "fs_of", fs_of)
    monkeypatch.setattr(pal_base, "storage_tools", lambda: {"btrfs": True, "zfs": True, "zpool": True, "mdadm": False})
    adapter = GenericLinuxStorageAdapter(pool_path=str(main))
    shares = [
        SimpleNamespace(name="films", mountpoint=str(main / "docs" / "films")),
        SimpleNamespace(name="music", mountpoint=str(main / "media" / "music")),
        SimpleNamespace(name="photos", mountpoint=str(main / "tank" / "photos")),
    ]
    monkeypatch.setattr(adapter, "list_shares", lambda: shares)
    ran = []

    def run(cmd):
        ran.append(cmd)
        if cmd[:2] == ["btrfs", "subvolume"] and cmd[2] == "snapshot":
            os.makedirs(cmd[-1], exist_ok=True)
        if cmd[:3] == ["zfs", "list", "-H"]:
            return 0, "tank/photos@a1\t1700000000\tphotos@auto-1\nelse/x@b\t1700000000\t-\n", ""
        return 0, "", ""

    monkeypatch.setattr(adapter, "_run_cmd", run)
    monkeypatch.setattr(
        gl, "zfs_mounts", lambda: {"tank/photos": str(main / "tank" / "photos"), "else/x": "/elsewhere"}
    )
    monkeypatch.setattr(gl, "zfs_dataset_at", lambda p: "tank/photos" if "/tank/photos" in str(p) else "")
    return SimpleNamespace(main=str(main), adapter=adapter, ran=ran)


def test_a_share_is_snapshotted_in_its_own_pool(box):
    a = box.adapter
    assert a.snapshot_pool_of("music") == "media" and a.snapshot_pool_of("films") == "docs"
    assert a.snapshot_pool_of("nobody") == ""
    res = a.create_snapshot("docs", "music", "music@auto-1")  # the pool asked for is not the share's
    assert res["status"] == "created"
    assert box.ran[-1] == [
        "btrfs",
        "subvolume",
        "snapshot",
        "-r",
        os.path.join(box.main, "media", "music"),
        os.path.join(box.main, "media", "@snapshots", "music@auto-1"),
    ]


def test_an_ext4_pool_keeps_no_snapshots(box):
    n = len(box.ran)
    res = box.adapter.create_snapshot("default", "films", "films@auto-1")
    assert res["status"] == "error" and "keeps no snapshots" in res["output"] and len(box.ran) == n
    assert box.adapter.share_can_snapshot("films") is False
    assert box.adapter.share_can_snapshot("music") is True
    assert box.adapter.share_can_snapshot("not-made-yet") is True


def test_the_default_listing_covers_every_pool(box):
    a = box.adapter
    a.create_snapshot("default", "music", "music@auto-1")
    os.makedirs(os.path.join(box.main, "@snapshots", "old@x"))  # the main folder's own, from before
    found = {(s["name"], s["pool_id"]) for s in a.list_snapshots("default")}
    assert found == {("music@auto-1", "media"), ("old@x", "default"), ("photos@auto-1", "tank")}
    assert {s["name"] for s in a.list_snapshots("media")} == {"music@auto-1"}
    assert {s["name"] for s in a.list_snapshots("tank")} == {"photos@auto-1"}


def test_delete_and_restore_in_the_pool_named(box):
    a = box.adapter
    a.create_snapshot("media", "music", "music@auto-1")
    res = a.delete_snapshot("media", "music@auto-1")
    assert res["status"] == "deleted"
    assert box.ran[-1] == [
        "btrfs",
        "subvolume",
        "delete",
        os.path.join(box.main, "media", "@snapshots", "music@auto-1"),
    ]
    a.create_snapshot("media", "music", "music@auto-2")
    res = a.restore_snapshot("media", "music@auto-2", "music")
    assert res["target"] == os.path.join(box.main, "media", "@shares", "music")


def test_pool_paths_and_the_snapshot_flag(box, monkeypatch):
    a = box.adapter
    assert a.get_pool_path("tank") == os.path.join(box.main, "tank")
    assert a.get_pool_path("default") == box.main
    assert a.get_pool_path("gone") == box.main
    monkeypatch.setattr(gl, "fs_of", lambda p: "ext4")  # the main folder is on the system disk
    assert a.get_capabilities().can_snapshot is True  # its pools have snapshots


def test_the_service_uses_the_share_pool(box, monkeypatch):
    monkeypatch.setattr(snapshot_service, "list_schedules", lambda: [])
    monkeypatch.setattr(box.adapter, "list_pools", lambda: [SimpleNamespace(id="docs")])
    assert snapshot_service._pool_of("music@auto-3", box.adapter) == "media"
    assert snapshot_service._pool_of("nobody", box.adapter) == "docs"  # the first pool, as before
    out = snapshot_service.take("music", {"keep": 5}, pal=box.adapter)
    assert out["ok"] is True
    monkeypatch.setattr(snapshot_service, "_pal", lambda: box.adapter)
    monkeypatch.setattr(snapshot_service, "availability", lambda pal=None: (True, ""))
    saved = []
    monkeypatch.setattr(snapshot_service, "save_schedule", lambda *a, **k: saved.append(a[0]))
    assert snapshot_service.ensure_default("films") is False and saved == []
    assert snapshot_service.ensure_default("music") is True and saved == ["music"]
