"""The check for a new drive (owner's decision, 19 Nov 2026): started by hand, read-only, only on a
drive that is not in use, with a verdict a person can act on."""

import errno
import os
import time
import types

import pytest

from backend.services import drive_check as dc
from backend.state import Z_STATE

MIB = 1024 * 1024


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A machine with three drives: sda in a pool, sdb mounted, sdc free (16 MiB), and an OS drive."""
    sys_block, dev_dir, proc = tmp_path / "sys" / "block", tmp_path / "dev", tmp_path / "proc"
    (proc / "1").mkdir(parents=True)
    dev_dir.mkdir()
    for name, sectors in (("sda", 1000), ("sdb", 1000), ("sdc", 16 * MIB // 512), ("nvme0n1", 1000)):
        (sys_block / name / "holders").mkdir(parents=True)
        (sys_block / name / "size").write_text(str(sectors))
        (dev_dir / name).write_bytes(os.urandom(sectors * 512) if name == "sdc" else b"")
    (sys_block / "sdb" / "sdb1" / "holders").mkdir(parents=True)
    (proc / "1" / "mounts").write_text("/dev/sdb1 /mnt/old ext4 rw 0 0\nproc /proc proc rw 0 0\n")
    (proc / "mounts").write_text("overlay / overlay rw 0 0\n")
    monkeypatch.setattr(dc, "HOST_SYS", str(tmp_path / "sys"))
    monkeypatch.setattr(dc, "HOST_PROC", str(proc))
    monkeypatch.setattr(dc, "DEV_DIR", str(dev_dir))
    monkeypatch.setattr(dc, "RESULTS_FILE", str(tmp_path / "checks.json"))
    monkeypatch.setattr(dc, "CHUNK", MIB)
    monkeypatch.setattr(dc, "SPEED_WINDOW_SECS", 0.0)
    pool = types.SimpleNamespace(members=[types.SimpleNamespace(device="sda")])
    monkeypatch.setattr(
        "backend.hardware.pal_storage.get_storage_platform", lambda: types.SimpleNamespace(list_pools=lambda: [pool])
    )
    disks = [{"dev": d, "role": "os" if d == "nvme0n1" else "data"} for d in ("sda", "sdb", "sdc", "nvme0n1")]
    monkeypatch.setattr(Z_STATE, "cached_stats", {"disks": disks})
    monkeypatch.setattr(Z_STATE, "cached_smart_data", {"sdc": (31, "ok")})
    readings = {"n": 0}

    def detail(dev, wake):
        readings["n"] += 1
        return {
            "serial": "SER123",
            "model": "Test 16M",
            "metrics": {"realloc": 0, "pending": 0, "offline": 0, "crc": 2},
        }

    monkeypatch.setattr("backend.hardware.disks.read_smart_detail", detail)
    events = []
    monkeypatch.setattr(
        "backend.state.add_event", lambda level, title, msg, details=None: events.append((level, details))
    )
    dc.reset_for_tests()
    yield types.SimpleNamespace(tmp=tmp_path, events=events, sys=sys_block, dev=dev_dir, readings=readings)
    dc.reset_for_tests()


def _wait(dev, seconds=20.0):
    end = time.time() + seconds
    while time.time() < end:
        if dev not in dc.active():
            return
        time.sleep(0.02)
    raise AssertionError("the check did not end")


def test_only_a_drive_that_is_not_in_use_is_offered(box):
    assert [(c["dev"], c["free"], c["in_use"]) for c in dc.candidates()] == [
        ("sda", False, "pool"),
        ("sdb", False, "mounted"),
        ("sdc", True, None),
        ("nvme0n1", False, "os"),
    ]
    for dev, key in (
        ("sda", "in_use_pool"),
        ("sdb", "in_use_mounted"),
        ("nvme0n1", "in_use_os"),
        ("sdz", "no_drive"),
        ("../x", "no_drive"),
    ):
        with pytest.raises(dc.NotNow) as refused:
            dc.start(dev)
        assert refused.value.key == key, dev
    (box.sys / "sdc" / "holders" / "md0").mkdir()
    assert dc.in_use("sdc") == "held"  # part of an array the pool list does not know
    assert dc.active() == {} and dc.results() == {}


def test_pools_that_cannot_be_read_mean_no_drive_is_offered(box, monkeypatch):
    def broken():
        raise RuntimeError("no platform")

    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", broken)
    assert dc.in_use("sdc") == "pool"  # not known to be free is not free


def test_before_the_first_reading_the_kernels_list_is_used(box, monkeypatch):
    monkeypatch.setattr(Z_STATE, "cached_stats", {})
    monkeypatch.setattr(dc, "OS_NVME", "nvme0n1")
    assert {d["dev"]: d["role"] for d in dc.drives()} == {"nvme0n1": "os", "sda": "", "sdb": "", "sdc": ""}


def test_a_good_drive_is_read_to_the_end_and_called_good(box):
    started = dc.start("sdc", "ana")
    assert started["state"] == "running" and started["size_bytes"] == 16 * MIB and "stop" not in started
    _wait("sdc")
    run = dc.results()["SER123"][0]
    assert (run["state"], run["verdict"], run["read_bytes"], run["unreadable"]) == ("finished", "good", 16 * MIB, 0)
    assert run["who"] == "ana" and run["before"]["serial"] == "SER123" and run["after"]["crc"] == 2
    assert run["slowest_bps"] > 0 and run["eta_secs"] is None and run["ended"] >= run["started"]
    assert box.readings["n"] == 2  # the drive's counters before and after
    assert box.events[0][0] == "info" and box.events[0][1]["msg_key"] == "ev.drive_check_good.msg"
    view = dc.view()
    sdc = next(d for d in view["drives"] if d["dev"] == "sdc")
    assert sdc["free"] and sdc["check"] is None and sdc["last"]["verdict"] == "good"
    assert next(d for d in view["drives"] if d["dev"] == "sda")["last"] is None


def test_places_that_cannot_be_read_make_it_bad(box, monkeypatch):
    real = os.preadv

    def flaky(fd, bufs, offset):
        if offset in (3 * MIB, 7 * MIB):
            raise OSError(errno.EIO, "Input/output error")
        return real(fd, bufs, offset)

    monkeypatch.setattr(dc.os, "preadv", flaky)
    dc.start("sdc")
    _wait("sdc")
    run = dc.results()["SER123"][0]
    assert (run["state"], run["verdict"], run["unreadable"], run["bad_places"]) == (
        "finished",
        "bad",
        2,
        [3 * MIB, 7 * MIB],
    )
    assert run["read_bytes"] == 16 * MIB  # it went on past them to the end
    assert box.events[0][0] == "warning" and box.events[0][1]["msg_key"] == "ev.drive_check_bad.msg"
    assert box.events[0][1]["params"]["count"] == 2


def test_counters_that_grew_while_it_was_read(box, monkeypatch):
    def run_with(after):
        calls = iter([{"realloc": 0, "pending": 0, "offline": 0, "crc": 2}, after])
        monkeypatch.setattr(
            "backend.hardware.disks.read_smart_detail", lambda d, w: {"serial": "S", "metrics": next(calls)}
        )
        dc.start("sdc")
        _wait("sdc")
        return dc.results()["S"][0]["verdict"]

    assert run_with({"realloc": 0, "pending": 0, "offline": 0, "crc": 9}) == "cable"  # the connection, not the drive
    assert run_with({"realloc": 8, "pending": 0, "offline": 0, "crc": 2}) == "bad"
    assert run_with({"realloc": 0, "pending": 1, "offline": 0, "crc": 9}) == "bad"  # worse wins
    assert dc.verdict({"state": "stopped", "unreadable": 0}) == "unfinished"
    assert len(dc.results()["S"]) == 3


def test_it_can_be_stopped_and_stops_itself_when_the_drive_is_hot(box, monkeypatch):
    real = os.preadv

    def slow(fd, bufs, offset):
        time.sleep(0.05)
        return real(fd, bufs, offset)

    monkeypatch.setattr(dc.os, "preadv", slow)
    dc.start("sdc")
    with pytest.raises(dc.NotNow) as twice:
        dc.start("sdc")
    assert twice.value.key == "running"
    going = dc.active()["sdc"]
    assert going["state"] == "running" and "stop" not in going
    assert dc.stop("sdc") is True
    _wait("sdc")
    run = dc.results()["SER123"][0]
    assert (run["state"], run["verdict"]) == ("stopped", "unfinished") and run["read_bytes"] < 16 * MIB
    assert dc.stop("sdc") is False
    assert box.events[-1][1]["msg_key"] == "ev.drive_check_stopped.msg"

    monkeypatch.setattr(Z_STATE, "cached_smart_data", {"sdc": (dc.heat_limit("sdc") + 1, "ok")})
    dc.start("sdc")
    _wait("sdc")
    run = dc.results()["SER123"][0]
    assert run["state"] == "too_hot" and run["verdict"] == "unfinished" and run["read_bytes"] < 16 * MIB
    assert box.events[-1][0] == "warning" and box.events[-1][1]["msg_key"] == "ev.drive_check_too_hot.msg"
    assert dc.heat_limit("nvme0n1") == dc.NVME_CRITICAL_TEMP - dc.HEAT_MARGIN_C


def test_a_drive_that_stops_answering_and_the_most_at_once(box, monkeypatch):
    def gone(fd, bufs, offset):
        raise OSError(errno.ENODEV, "No such device")

    monkeypatch.setattr(dc.os, "preadv", gone)
    dc.start("sdc")
    _wait("sdc")
    run = dc.results()["SER123"][0]
    assert (run["state"], run["verdict"], run["after"]) == ("failed", "unfinished", {}) and "No such device" in run[
        "why"
    ]
    assert box.events[-1][1]["msg_key"] == "ev.drive_check_failed.msg"
    monkeypatch.setattr(dc, "MAX_AT_ONCE", 0)
    with pytest.raises(dc.NotNow) as busy:
        dc.start("sdc")
    assert busy.value.key == "busy"


def test_only_the_last_results_of_a_drive_are_kept(box, monkeypatch):
    monkeypatch.setattr(dc, "RESULTS_KEPT", 2)
    for _ in range(3):
        dc.start("sdc")
        _wait("sdc")
    assert len(dc.results()["SER123"]) == 2


def test_the_api(box, client, auth_headers, monkeypatch):
    view = client.get("/api/drives/check", headers=auth_headers).json()
    assert [d["dev"] for d in view["drives"] if d["free"]] == ["sdc"] and view["max_at_once"] == 2
    refused = client.post("/api/drives/sda/check", headers=auth_headers)
    assert refused.status_code == 409 and refused.json()["error"] == "drive_check_in_use_pool"
    assert refused.json()["text"]["msg_key"] == "srv.drive_check_in_use_pool"
    assert client.post("/api/drives/..%2Fetc/check", headers=auth_headers).status_code in (404, 422)
    started = client.post("/api/drives/sdc/check", headers=auth_headers).json()
    assert started["status"] == "started" and started["check"]["who"] == "admin"
    _wait("sdc")
    assert client.post("/api/drives/sdc/check/stop", headers=auth_headers).json() == {"stopped": False}
    assert client.get("/api/drives/check", headers=auth_headers).json()["drives"][2]["last"]["verdict"] == "good"
    monkeypatch.setattr(
        "backend.auth.get_current_session",
        lambda tok: {
            "user_id": "u",
            "username": "sam",
            "role_id": "auditor",
            "scopes": ["storage:read", "system:view"],
        },
    )
    reader = {"Authorization": "Bearer x"}
    assert client.get("/api/drives/check", headers=reader).status_code == 200  # anyone who may see the drives
    assert client.post("/api/drives/sdc/check", headers=reader).status_code == 403
    assert client.post("/api/drives/sdc/check/stop", headers=reader).status_code == 403


@pytest.mark.real_confirmations
def test_starting_is_confirmed(box, client, auth_headers):
    ask = client.post("/api/drives/sdc/check", headers=auth_headers)
    assert ask.status_code == 428 and ask.json()["action"] == "disk.surface_check" and ask.json()["target"] == "sdc"
    assert dc.active() == {}
    token = client.post(
        "/api/confirmations", json={"action": "disk.surface_check", "target": "sdc"}, headers=auth_headers
    ).json()["token"]
    assert client.post("/api/drives/sdc/check", headers={**auth_headers, "X-Confirm-Token": token}).status_code == 200
    _wait("sdc")


def test_the_drive_is_named_by_the_kernel_not_by_the_request(tmp_path, monkeypatch):
    """Code scanning 531-534: what goes into a path is the kernel's own name for the drive."""
    from backend.services import drive_check as dc

    (tmp_path / "block" / "sdb").mkdir(parents=True)
    monkeypatch.setattr(dc, "HOST_SYS", str(tmp_path))
    asked = "sd" + "b"
    assert dc.kernel_name(asked) == "sdb"
    assert dc.kernel_name("sdc") is None  # a valid name, no such drive
    for bad in ("../sdb", "sdb/../sdb", "sdb1", "", "SDB", "sdb\n"):
        assert dc.kernel_name(bad) is None, bad
    monkeypatch.setattr(dc, "HOST_SYS", str(tmp_path / "nowhere"))
    assert dc.kernel_name("sdb") is None
