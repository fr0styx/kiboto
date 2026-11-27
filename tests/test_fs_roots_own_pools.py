"""On Kiboto OS the file manager lists the pools Kiboto made, not folders it finds in /mnt. The list
was guessed Unraid's way: Kiboto OS's own pools (under the storage folder) were missing, and any
folder in /mnt, Kiboto's own place for opened encrypted folders among them, was called a pool."""

from backend import runtime
from backend.hardware.pal import pool_registry


def test_on_kiboto_os_the_pools_are_kibotos_own(client, auth_headers, monkeypatch, tmp_path):
    tank = tmp_path / "tank"
    tank.mkdir()
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    monkeypatch.setattr(
        pool_registry,
        "load",
        lambda: [
            {"name": "tank", "mountpoint": str(tank)},
            {"name": "away", "mountpoint": str(tmp_path / "away")},
            {"name": "gone", "mountpoint": str(tmp_path / "gone"), "ejected": True},
            {"name": "nowhere"},
        ],
    )
    pools = client.get("/api/fs/roots", headers=auth_headers).json()["pools"]
    own = [p for p in pools if not p["path"].startswith("/mnt/disks")]
    assert own == [
        {"name": "tank", "path": str(tank), "available": True},
        {"name": "away", "path": str(tmp_path / "away"), "available": True},  # by the record: no folder is looked at
    ]


def test_elsewhere_the_folders_in_mnt_are_still_offered(client, auth_headers, monkeypatch):
    monkeypatch.setattr(runtime, "managed_host", lambda: False)
    monkeypatch.setattr(pool_registry, "load", lambda: [{"name": "tank", "mountpoint": "/nowhere/tank"}])
    pools = client.get("/api/fs/roots", headers=auth_headers).json()["pools"]
    assert all(p["path"] != "/nowhere/tank" for p in pools)
