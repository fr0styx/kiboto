"""Kiboto OS: what only root may read (the pools that could be imported, the kernel's log) is read
in the host door; the web process got "permission denied" and showed nothing."""

from backend import door
from backend.hardware import kernel_telemetry
from backend.hardware.pal import generic_linux as gl
from backend.services import host_door


def test_pools_to_import_are_listed_through_the_door(monkeypatch):
    asked = []
    monkeypatch.setattr(gl, "_through_door", lambda op, here, **kw: asked.append(op) or [{"pool_id": "old"}])
    adapter = gl.GenericLinuxStorageAdapter.__new__(gl.GenericLinuxStorageAdapter)
    assert adapter.discover_external_pools() == [{"pool_id": "old"}] and asked == ["storage.discover_pools"]
    assert "storage.discover_pools" in host_door.OPERATIONS


def test_the_kernels_log_comes_through_the_door(monkeypatch):
    asked = []

    def via(op, here, **kw):
        asked.append((op, kw))
        return {"available": True, "alerts": [], "recent_lines": ["x"]}

    monkeypatch.setattr(door, "via", via)
    assert kernel_telemetry.get_categorized_dmesg(50)["recent_lines"] == ["x"]
    assert asked == [("diagnostics.dmesg", {"max_lines": 50})]


def test_a_door_that_refuses_says_the_log_is_not_there(monkeypatch):
    def refuses(op, here, **kw):
        raise RuntimeError("refused")

    monkeypatch.setattr(door, "via", refuses)
    got = kernel_telemetry.get_categorized_dmesg()
    assert got["available"] is False and got["recent_lines"] == []


def test_the_door_keeps_the_length_in_bounds(monkeypatch):
    seen = []
    monkeypatch.setattr(kernel_telemetry, "dmesg_here", lambda n: seen.append(n) or {"available": True})
    host_door._dmesg(10**9)
    host_door._dmesg(0)
    assert seen == [1000, 1]
