"""Are your files safe? (SET-21 stage 1, Backup decision 1 A)."""

import pytest

from backend.services import backup_verdict as bv

NOW = 1_800_000_000.0
DAY = 86400


@pytest.fixture
def world(monkeypatch):
    state = {"repos": [], "copies": [], "rows": []}
    monkeypatch.setattr(bv, "_repos", lambda: state["repos"])
    monkeypatch.setattr(bv, "copies", lambda: state["copies"])
    monkeypatch.setattr(bv, "_protection_rows", lambda now: state["rows"])
    return state


def repo(**kw):
    base = {
        "id": "r1",
        "name": "Office disk",
        "location": "rclone:b2:kiboto",
        "initialized": True,
        "last_backup": NOW - DAY,
        "last_result": "ok",
        "kit_saved_at": NOW - 10 * DAY,
        "same_disk": False,
    }
    return {**base, **kw}


def copy(**kw):
    return {"name": "Office disk", "kind": "cloud", "engine": "offsite", "last_ok": NOW - DAY, **kw}


def test_nothing_set_up(world):
    assert bv.verdict(NOW) == {"level": "none", "newest": None, "issues": []}


def test_fine_with_a_fresh_copy_outside_and_nothing_to_look_at(world):
    world["repos"] = [repo()]
    world["copies"] = [copy()]
    v = bv.verdict(NOW)
    assert v["level"] == "fine" and v["issues"] == []
    assert v["newest"] == {"name": "Office disk", "kind": "cloud", "when": NOW - DAY}


def test_a_failed_run_is_failed(world):
    world["repos"] = [repo(last_result="Fatal: unable to open repository")]
    world["copies"] = [copy()]
    v = bv.verdict(NOW)
    assert (
        v["level"] == "failed" and v["issues"][0]["kind"] == "failed" and "unable to open" in v["issues"][0]["detail"]
    )


def test_what_needs_a_look(world):
    world["repos"] = [
        repo(id="late", last_backup=NOW - 5 * DAY),
        repo(id="never", last_backup=None),
        repo(id="same", location="/mnt/user/backups", same_disk=True),
        repo(id="here", location="/mnt/user/other", same_disk=False),
        repo(id="kit", kit_saved_at=None),
        repo(id="read", last_unreadable=3),
        repo(id="drill", last_drill_result="failed: restored file differs"),
        repo(id="small", last_drill_result="no file small enough to test"),
    ]
    world["copies"] = [copy()]
    kinds = {(i["id"], i["kind"]) for i in bv.verdict(NOW)["issues"]}
    assert kinds == {
        ("late", "late"),
        ("never", "late"),
        ("same", "same_disk"),
        ("here", "here_only"),
        ("kit", "kit"),
        ("read", "unreadable"),
        ("drill", "drill"),
    }
    assert bv.verdict(NOW)["level"] == "look"


def test_a_usb_disk_gets_a_week(world):
    world["repos"] = [repo(location="/mnt/disks/usb1/kiboto", last_backup=NOW - 5 * DAY)]
    world["copies"] = [copy(kind="usb", last_ok=NOW - 5 * DAY)]
    assert bv.verdict(NOW)["level"] == "fine"
    world["repos"] = [repo(location="/mnt/disks/usb1/kiboto", last_backup=NOW - 8 * DAY)]
    world["copies"] = [copy(kind="usb", last_ok=NOW - 8 * DAY)]
    assert bv.verdict(NOW)["level"] == "look"


def test_copy_jobs_and_replication_count_and_can_be_late(world):
    world["copies"] = [
        copy(name="Nightly copy", engine="copy", last_ok=NOW - DAY),
        copy(name="To the other box", kind="nas", engine="replication", last_ok=None),
    ]
    v = bv.verdict(NOW)
    assert v["level"] == "look"
    assert v["issues"] == [
        {"name": "To the other box", "id": None, "engine": "replication", "kind": "late", "since": None}
    ]
    assert v["newest"]["name"] == "Nightly copy"


def test_what_the_old_table_watched_has_lines(world):
    world["copies"] = [copy(name="Nightly copy", engine="copy"), copy()]
    world["rows"] = [
        {"kind": "backup", "id": "j1", "name": "Nightly copy", "status": "failed", "why": "failed: rclone exited 1"},
        {"kind": "backup", "id": "j2", "name": "Fine job", "status": "ok", "why": ""},
        {"kind": "offsite", "id": "r1", "name": "Office disk", "status": "overdue", "why": "late"},
        {"kind": "snapshot", "id": "photos", "name": "photos", "status": "overdue", "why": ""},
        {"kind": "snapshot", "id": "docs", "name": "docs", "status": "unavailable", "why": "no tools"},
        {"kind": "scrub", "id": "p1", "name": "tank", "status": "overdue", "errors": 0},
        {"kind": "scrub", "id": "p2", "name": "cache", "status": "ok", "errors": 3},
        {"kind": "scrub", "id": "p3", "name": "array", "status": "host_owned", "errors": 0},
    ]
    v = bv.verdict(NOW)
    got = [(i["name"], i["kind"]) for i in v["issues"]]
    assert got == [
        ("Nightly copy", "failed"),
        ("photos", "snap_late"),
        ("tank", "check_late"),
        ("cache", "check_errors"),
    ]
    assert v["level"] == "failed" and v["issues"][3]["count"] == 3


def test_a_failed_snapshot_is_failed_and_snapshots_alone_are_set_up(world):
    world["rows"] = [{"kind": "snapshot", "id": "photos", "name": "photos", "status": "ok"}]
    assert bv.verdict(NOW)["level"] == "look"  # set up, but nothing outside this Kiboto
    world["rows"] = [
        {"kind": "snapshot", "id": "photos", "name": "photos", "status": "failed", "why": "failed: no space"}
    ]
    assert bv.verdict(NOW)["level"] == "failed"


def test_a_disk_check_alone_is_not_a_backup(world):
    world["rows"] = [{"kind": "scrub", "id": "p1", "name": "tank", "status": "ok", "errors": 0}]
    assert bv.verdict(NOW)["level"] == "none"


def test_unreadable_backups_count_as_none_set_up(monkeypatch):
    def broken():
        raise OSError("disk gone")

    monkeypatch.setattr("backend.services.offsite_backup.list_repos", broken)
    monkeypatch.setattr(bv, "copies", lambda: [])
    monkeypatch.setattr(bv, "_protection_rows", lambda now: [])
    assert bv.verdict(NOW)["level"] == "none"


def test_the_route_answers(client, auth_headers, world):
    world["repos"] = [repo()]
    world["copies"] = [copy(last_ok=None)]
    r = client.get("/api/system/protection/verdict", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["level"] in ("look", "fine", "failed", "none")
