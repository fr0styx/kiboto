"""Re-audit R6: a check (scrub) that finds damage says which files (ZFS)."""

from types import SimpleNamespace

from backend.hardware.pal.scrub_parse import parse_zpool_damaged, parse_zpool_scan
from backend.services import pool_alerts

DAMAGED = """  pool: tank
 state: ONLINE
status: One or more devices has experienced an error resulting in data
        corruption.  Applications may be affected.
  scan: scrub repaired 0B in 02:10:11 with 3 errors on Sun Nov 15 03:10:12 2026
config:

        NAME        STATE     READ WRITE CKSUM
        tank        ONLINE       0     0     0
          sda       ONLINE       0     0     6

errors: Permanent errors have been detected in the following files:

        /mnt/tank/photos/2024/IMG_0001.jpg
        /mnt/tank/photos/2024/IMG 0002.jpg
        tank/data@snap1:/old/report.pdf
        <metadata>:<0x1a>
        tank/vm:<0x8>
"""
CLEAN = """  pool: tank
 state: ONLINE
  scan: scrub repaired 0B in 02:10:11 with 0 errors on Sun Nov 15 03:10:12 2026
config:

        NAME        STATE     READ WRITE CKSUM
        tank        ONLINE       0     0     0

errors: No known data errors
"""


def test_the_files_zfs_names_are_read_and_the_rest_is_counted():
    out = parse_zpool_damaged(DAMAGED)
    assert out["files"] == [
        "/mnt/tank/photos/2024/IMG_0001.jpg",
        "/mnt/tank/photos/2024/IMG 0002.jpg",
        "tank/data@snap1:/old/report.pdf",
    ]
    assert out["count"] == 3 and out["other"] == 2  # metadata and an object without a name
    assert parse_zpool_damaged(CLEAN) == {"files": [], "count": 0, "other": 0}
    assert parse_zpool_damaged("") == {"files": [], "count": 0, "other": 0}
    assert parse_zpool_scan(DAMAGED)["errors"] == 3  # the scan line is read as before


def test_a_long_list_is_cut_but_counted():
    many = "errors: Permanent errors have been detected in the following files:\n\n" + "".join(
        f"        /mnt/tank/f{i}.bin\n" for i in range(250)
    )
    out = parse_zpool_damaged(many)
    assert out["count"] == 250 and len(out["files"]) == 100


def _pool():
    return SimpleNamespace(id="tank", name="tank", status="HEALTHY", members=[], used_pct=10, total_bytes=1)


def test_damaged_files_are_a_problem_of_their_own_with_names():
    scrub = {"state": "finished", "errors": 3, "damaged": parse_zpool_damaged(DAMAGED)}
    items = pool_alerts.problems([_pool()], {"tank": scrub})
    damaged = next(i for i in items if i["kind"] == "damaged_files")
    assert damaged["level"] == "critical" and damaged["detail"] == "3" and damaged["subject"] == "tank"
    assert damaged["files"] == "IMG_0001.jpg, IMG 0002.jpg, report.pdf"
    assert any(i["kind"] == "scrub_errors" for i in items)
    title, message = pool_alerts._text(damaged)
    assert title == "Damaged files in tank: 3"
    assert "IMG_0001.jpg" in message and "backup or a snapshot" in message
    # nothing named: the count of errors is all there is to say
    none = pool_alerts.problems(
        [_pool()], {"tank": {"state": "finished", "errors": 1, "damaged": {"files": [], "count": 0, "other": 1}}}
    )
    assert [i["kind"] for i in none] == ["scrub_errors"]
    assert pool_alerts.problems([_pool()], {"tank": {"state": "finished", "errors": 0}}) == []


def test_more_than_three_names_say_how_many_more():
    files = [f"/mnt/tank/f{i}.bin" for i in range(5)]
    items = pool_alerts.problems(
        [_pool()], {"tank": {"errors": 5, "damaged": {"files": files, "count": 5, "other": 0}}}
    )
    damaged = next(i for i in items if i["kind"] == "damaged_files")
    assert damaged["files"] == "f0.bin, f1.bin, f2.bin (+2)"


def test_the_adapter_asks_zfs_for_the_names_and_the_route_lists_them(client, monkeypatch):
    from backend.hardware.pal.base import StoragePlatformAdapter

    asked = []

    def run(self, cmd, *a, **k):
        asked.append(cmd)
        return 0, DAMAGED, ""

    adapter = SimpleNamespace(_run_cmd=lambda cmd, *a, **k: run(None, cmd))
    pool = SimpleNamespace(id="tank", fs_type="zfs", pool_type="zfs_pool", mountpoint="/mnt/tank")
    out = StoragePlatformAdapter.scrub_result(adapter, pool)
    assert asked == [["zpool", "status", "-v", "tank"]]
    assert out["errors"] == 3 and out["damaged"]["count"] == 3

    monkeypatch.setattr(pool_alerts, "_read", lambda: ([_pool()], {"tank": out}))
    assert client.get("/api/storage/damaged-files").status_code in (401, 403)
    h = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'password': 'admin'}).json()['token']}"}
    res = client.get("/api/storage/damaged-files", headers=h)
    assert res.status_code == 200
    assert res.json() == {"pools": [{"pool": "tank", "count": 3, "other": 2, "files": out["damaged"]["files"]}]}
    monkeypatch.setattr(pool_alerts, "_read", lambda: ([_pool()], {"tank": {"errors": 0}}))
    assert client.get("/api/storage/damaged-files", headers=h).json() == {"pools": []}

    def broken():
        raise OSError("zpool is not answering")

    monkeypatch.setattr(pool_alerts, "_read", broken)
    assert client.get("/api/storage/damaged-files", headers=h).json() == {"pools": []}
