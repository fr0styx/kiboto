"""Pool and snapshot write paths say what happened.

A forced disconnect answered "destroyed" although nothing on the drives changes, and for a ZFS pool
it only unmounted one folder, leaving the pool imported. Deleting or restoring a snapshot answered
"deleted" or "restored" when the file system's tool was missing, and a failed restore left the live
folder set aside under another name."""

import json
import time

import pytest

from backend.hardware.pal.base import StoragePool
from backend.hardware.pal_storage import GenericLinuxStorageAdapter


def _pool(pool_id, fs_type, mountpoint):
    kind = {"zfs": "zfs_pool"}.get(fs_type, "single")
    return StoragePool(id=pool_id, name=pool_id, pool_type=kind, fs_type=fs_type, mountpoint=mountpoint)


@pytest.fixture
def box(tmp_path):
    """A main pool in tmp_path plus a ZFS, an ext4 and an unmounted XFS pool; `codes` sets a tool's exit code."""
    adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path))
    ran, codes = [], {}

    def run(cmd):
        ran.append(cmd)
        code = codes.get(cmd[0], 0)
        return code, "", (f"Command not found: {cmd[0]}" if code == 127 else "")

    adapter._run_cmd = run
    adapter.list_pools = lambda: [
        _pool("tank", "zfs", "/mnt/tank"),
        _pool("md0", "ext4", "/mnt/pools/archive"),
        _pool("sdx1", "xfs", ""),
    ]
    adapter._zfs_snapshots = lambda pool_id: []
    return adapter, ran, codes, tmp_path


def test_a_zfs_pool_is_exported_not_only_unmounted(box):
    adapter, ran, _codes, _tmp = box
    res = adapter.destroy_pool("tank")
    assert ran == [["zpool", "export", "-f", "tank"]]
    assert res["status"] == "disconnected" and res["pool_id"] == "tank"


def test_another_pool_is_unmounted_and_says_disconnected(box):
    adapter, ran, codes, _tmp = box
    assert adapter.destroy_pool("md0")["status"] == "disconnected"
    assert ran == [["umount", "-f", "/mnt/pools/archive"]]
    codes["umount"] = 1
    with pytest.raises(RuntimeError, match="md0 could not be disconnected"):
        adapter.destroy_pool("md0")


def test_a_pool_that_is_not_mounted_has_nothing_to_disconnect(box):
    adapter, ran, _codes, _tmp = box
    with pytest.raises(RuntimeError, match="nothing to disconnect"):
        adapter.destroy_pool("sdx1")
    assert ran == []


@pytest.mark.parametrize("code", [127, 1])
def test_a_snapshot_that_was_not_deleted_is_an_error_and_keeps_its_lock_record(box, code):
    adapter, _ran, codes, tmp = box
    snaps = tmp / "@snapshots"
    snaps.mkdir()
    meta = snaps / ".docs_2026.worm.json"
    meta.write_text(json.dumps({"worm_mode": "governance", "retention_until": time.time() - 60}))
    codes["btrfs"] = code
    res = adapter.delete_snapshot("default_pool", "docs_2026")
    assert res["status"] == "error" and res["code"] == code and res["message"]
    assert meta.exists()
    codes["btrfs"] = 0
    res = adapter.delete_snapshot("default_pool", "docs_2026")
    assert res["status"] == "deleted" and "message" not in res
    assert not meta.exists()


@pytest.mark.parametrize("code", [127, 1])
def test_a_failed_restore_puts_the_live_folder_back(box, code):
    adapter, _ran, codes, tmp = box
    (tmp / "@snapshots" / "docs_2026").mkdir(parents=True)
    live = tmp / "@shares" / "docs"
    live.mkdir(parents=True)
    (live / "a.txt").write_text("still here")
    codes["btrfs"] = code
    res = adapter.restore_snapshot("default_pool", "docs_2026")
    assert res["status"] == "error" and res["archived_previous"] is None
    assert (live / "a.txt").read_text() == "still here"
    assert [p.name for p in (tmp / "@shares").iterdir()] == ["docs"]


def test_a_restore_that_worked_keeps_the_old_folder_aside(box):
    adapter, _ran, _codes, tmp = box
    (tmp / "@snapshots" / "docs_2026").mkdir(parents=True)
    live = tmp / "@shares" / "docs"
    live.mkdir(parents=True)
    res = adapter.restore_snapshot("default_pool", "docs_2026")
    assert res["status"] == "restored"
    assert res["archived_previous"].startswith(str(live) + ".pre_restore.")


def test_the_route_refuses_when_nothing_was_deleted(client, auth_headers, monkeypatch, tmp_path):
    adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path))
    monkeypatch.setattr("backend.api.storage.get_storage_platform", lambda: adapter)
    monkeypatch.setattr(adapter, "_zfs_snapshots", lambda pool_id: [])
    monkeypatch.setattr(adapter, "_run_cmd", lambda cmd: (127, "", "Command not found: btrfs"))
    r = client.delete("/api/storage/pools/default_pool/snapshots/docs_2026", headers=auth_headers)
    assert r.status_code == 409 and "btrfs" in r.json()["detail"]
    monkeypatch.setattr(adapter, "_run_cmd", lambda cmd: (0, "", ""))
    r = client.delete("/api/storage/pools/default_pool/snapshots/docs_2026", headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "deleted"
