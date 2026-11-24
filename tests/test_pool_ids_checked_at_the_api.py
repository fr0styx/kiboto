"""A pool id is a name at the API too, also where Kiboto runs the storage tools itself (without
the host door, which checks the same): no leading / and no .. segment."""

import pytest


@pytest.mark.parametrize("pool_id", ["/etc", "tank/../../etc", "..", "-x"])
def test_a_snapshot_names_a_pool_not_a_path(client, auth_headers, pool_id):
    r = client.post("/api/backup/snapshots", json={"pool_id": pool_id, "subvol_name": "photos"}, headers=auth_headers)
    assert r.status_code == 422


def test_a_rename_names_a_pool_not_a_path(client, auth_headers):
    r = client.post("/api/storage/pools/tank%2F..%2F..%2Fetc/rename", json={"new_name": "x"}, headers=auth_headers)
    assert r.status_code in (404, 422)  # never reaches the storage tools


def test_a_tool_that_cannot_start_names_itself_not_the_error(monkeypatch):
    from backend.hardware import drive_sleep

    def gone(cmd, **k):
        raise FileNotFoundError(2, "No such file or directory", "/usr/sbin/hdparm")

    monkeypatch.setattr(drive_sleep, "run_bounded", gone)
    assert drive_sleep.run(["/usr/sbin/hdparm", "-S", "0", "/dev/sda"]) == (127, "hdparm could not be started")
