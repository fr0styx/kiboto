"""Kiboto OS: btrfs gives its last scrub only to root, so pool alerts read it through the host door;
without that, scrub errors on a btrfs pool never reached anyone."""

from types import SimpleNamespace

from backend import runtime
from backend.hardware.pal import generic_linux as gl
from backend.services import host_door

BTRFS = SimpleNamespace(id="media", fs_type="btrfs", pool_type="btrfs_raid", mountpoint="/mnt/storage/media")


def _adapter():
    return gl.GenericLinuxStorageAdapter.__new__(gl.GenericLinuxStorageAdapter)


def test_without_root_a_btrfs_pools_scrub_is_read_through_the_door(monkeypatch):
    asked = []

    def door(op, here, **kw):
        asked.append((op, kw))
        return {"state": "finished", "errors": 3}

    monkeypatch.setattr(runtime, "without_root", lambda: True)
    monkeypatch.setattr(gl, "_through_door", door)
    assert _adapter().scrub_result(BTRFS) == {"state": "finished", "errors": 3}
    assert asked == [("storage.scrub_result", {"pool_id": "media"})]


def test_the_door_reads_it_with_btrfs_itself(monkeypatch):
    monkeypatch.setattr(runtime, "without_root", lambda: False)  # the door is root
    a = _adapter()
    monkeypatch.setattr(a, "resolve_pool", lambda pool_id: BTRFS)
    monkeypatch.setattr(a, "_run_cmd", lambda cmd: (0, "Status: finished\n\tcsum_errors: 2\n", ""), raising=False)
    assert a.scrub_result_of("media")["errors"] == 2
    assert a._scrub_result_here("media")["errors"] == 2


def test_the_door_has_the_operation():
    assert "storage.scrub_result" in host_door.OPERATIONS
