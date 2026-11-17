"""Backup 5: which shared folders have a copy outside this NAS; folders left out on purpose."""

from types import SimpleNamespace

import pytest

from backend import config
from backend.services import protection_status as ps


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))


SHARES = [
    {"name": "photos", "path": "/mnt/user/photos"},
    {"name": "docs", "path": "/mnt/user/docs"},
    {"name": "tmp", "path": "/mnt/user/tmp"},
]


def test_whole_part_none_and_left_out():
    sources = [
        {"name": "Nightly", "paths": ["/mnt/user/photos"], "last_ok": 100.0},
        {"name": "Cloud", "paths": ["/mnt/user/docs/taxes"], "last_ok": None},
        {"name": "Empty", "paths": [""], "last_ok": None},
    ]
    ps.set_left_out("tmp", True)
    rows = {r["name"]: r for r in ps.folder_coverage(SHARES, sources)}
    assert rows["photos"]["copies"] == [{"name": "Nightly", "last_ok": 100.0}] and rows["photos"]["partly"] == []
    assert rows["docs"]["copies"] == [] and rows["docs"]["partly"] == [{"name": "Cloud", "last_ok": None}]
    assert rows["tmp"]["left_out"] is True and rows["tmp"]["copies"] == []
    # the whole pool covers every folder; /mnt/user/photosx is another folder
    pool = {
        r["name"]: r
        for r in ps.folder_coverage(
            SHARES + [{"name": "px", "path": "/mnt/user/photosx"}], [{"name": "All", "paths": ["/mnt/user"]}]
        )
    }
    assert all(r["copies"] for r in pool.values())
    assert (
        ps.folder_coverage(
            [{"name": "px", "path": "/mnt/user/photosx"}], [{"name": "P", "paths": ["/mnt/user/photos"]}]
        )[0]["copies"]
        == []
    )


def test_the_left_out_list_is_kept():
    assert ps.left_out() == []
    assert ps.set_left_out("tmp", True) == ["tmp"]
    assert ps.set_left_out("dl", True) == ["dl", "tmp"]
    assert ps.set_left_out("tmp", False) == ["dl"]


def test_copy_sources_from_all_three_kinds(monkeypatch):
    monkeypatch.setattr(
        "backend.services.offsite_backup.list_repos",
        lambda: [
            {
                "id": "u",
                "name": "USB",
                "location": "/mnt/disks/x/kiboto-backup",
                "paths": ["/mnt/user/photos"],
                "last_backup": 5,
            },
            {"id": "h", "name": "Here", "location": "/mnt/user/backups", "paths": ["/mnt/user/docs"]},
        ],
    )
    monkeypatch.setattr(
        "backend.services.backup_engine.get_backup_jobs",
        lambda: [
            {
                "name": "Copy",
                "destination_type": "remote",
                "source_pool": "p",
                "source_subvolume": "docs",
                "last_success_at": 7,
            },
            {"name": "Whole", "destination_type": "remote", "source_pool": "p", "source_subvolume": ""},
            {"name": "Local", "destination_type": "local"},
            {"name": "Off", "destination_type": "remote", "enabled": False},
            {"name": "Cfg", "kind": "config", "destination_type": "remote"},
        ],
    )
    monkeypatch.setattr(
        "backend.services.replication_engine.get_replication_engine",
        lambda: SimpleNamespace(
            list_jobs=lambda: [
                {
                    "name": "Rep",
                    "target_type": "remote",
                    "source_pool": "p",
                    "source_dataset": "photos",
                    "last_success": 9,
                },
                {"name": "LocalRep", "target_type": "local"},
            ]
        ),
    )
    names = {s["name"]: s for s in ps._copy_sources(lambda pool: "/mnt/pool")}
    assert set(names) == {"USB", "Copy", "Whole", "Rep"}
    assert names["Copy"]["paths"] == ["/mnt/pool/@shares/docs", "/mnt/pool/docs"]
    assert names["Whole"]["paths"] == ["/mnt/pool"] and names["Rep"]["paths"] == ["/mnt/pool/photos"]


def test_routes(client, auth_headers, monkeypatch):
    shares = [
        SimpleNamespace(name="photos", mountpoint="/mnt/user/photos"),
        SimpleNamespace(name="ghost", mountpoint=""),
    ]
    monkeypatch.setattr(
        "backend.hardware.pal_storage.get_storage_platform", lambda: SimpleNamespace(list_shares=lambda: shares)
    )
    monkeypatch.setattr(ps, "_copy_sources", lambda pool_path=None: [])
    body = client.get("/api/system/protection/folders", headers=auth_headers).json()
    assert [f["name"] for f in body["folders"]] == ["photos"]
    r = client.put(
        "/api/system/protection/folders/left-out", json={"name": "photos", "left_out": True}, headers=auth_headers
    )
    assert r.json() == {"left_out": ["photos"]}
