"""Kiboto makes ZFS, btrfs and ext4 pools. XFS is not offered for a new pool, and a kind it does not
make is refused before any command runs (it used to fall through and answer "provisioned")."""

import pytest

from backend.hardware.pal.generic_linux import POOL_KINDS
from backend.hardware.pal_storage import GenericLinuxStorageAdapter


def _adapter(tmp_path, ran):
    adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path))
    adapter._resolve_disk_path = lambda d: d
    adapter._run_cmd = lambda cmd: (ran.append(cmd), (0, "", ""))[1]
    return adapter


def test_the_kinds_on_offer(monkeypatch):
    assert POOL_KINDS == ("zfs", "btrfs", "ext4")
    tools = dict.fromkeys(("btrfs", "zfs", "zpool", "mdadm"), True)
    monkeypatch.setattr("backend.hardware.pal.base.storage_tools", lambda: tools)
    assert GenericLinuxStorageAdapter().get_capabilities().supported_filesystems == ["btrfs", "ext4", "zfs"]


@pytest.mark.parametrize("kind", ["xfs", "XFS", "ntfs", ""])
def test_a_kind_kiboto_does_not_make_runs_nothing(tmp_path, kind):
    ran = []
    with pytest.raises(ValueError, match="Kiboto makes zfs, btrfs, ext4 pools"):
        _adapter(tmp_path, ran).create_pool(
            name="p1", fs_type=kind, profile="single", disks=["/dev/zza"], mountpoint=str(tmp_path / "p1")
        )
    assert ran == []


def test_the_route_refuses_xfs(client, auth_headers, monkeypatch, tmp_path):
    # whatever platform an earlier test left behind: this is about a machine Kiboto manages
    adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path))
    monkeypatch.setattr("backend.api.storage.get_storage_platform", lambda: adapter)
    body = {
        "name": "films",
        "fs_type": "xfs",
        "profile": "single",
        "disks": ["sdz"],
        "confirm_name": "films",
        "current_password": "admin",
    }
    r = client.post("/api/storage/pools", json=body, headers=auth_headers)
    assert r.status_code == 400 and "ZFS, btrfs and ext4" in r.json()["detail"]


def test_the_create_dialog_does_not_offer_xfs():
    with open("frontend/src/windows/management-window.html", encoding="utf-8") as f:
        page = f.read()
    box = page[page.index('id="create-pool-fs"') :]
    box = box[: box.index("</select>")]
    assert 'value="xfs"' not in box and all(f'value="{k}"' in box for k in POOL_KINDS)
