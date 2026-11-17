"""The Overview's "too hot" says what is too hot (Hardware 3, the status sentence), from the last
readings the fans used: awake drives at their limit and the processor at 80 °C; a sleeping drive is
never named (or woken)."""

from backend.services import status_summary
from backend.state import Z_STATE


def _hot(monkeypatch, stats, active=True):
    monkeypatch.setattr(Z_STATE, "critical_temp_active", active, raising=False)
    monkeypatch.setattr(Z_STATE, "cached_stats", stats, raising=False)
    return [i for i in status_summary._power() if i["kind"] == "too_hot"]


def test_it_names_the_hot_drives_and_the_processor(monkeypatch):
    stats = {
        "disks": [
            {"name": "sdb", "temp": 57.4},
            {"name": "sdc", "temp": 61, "standby": True},
            {"name": "sdd", "temp": 41},
            {"dev": "nvme0n1", "temp": 74},
            {"dev": "nvme1n1", "temp": 76, "is_nvme": True},
            {"name": "sde", "temp": None},
        ],
        "cpu": {"temp": 81.6},
    }
    (item,) = _hot(monkeypatch, stats)
    assert item["level"] == "critical"
    assert item["hot"] == {"drives": [{"name": "sdb", "temp": 57}, {"name": "nvme1n1", "temp": 76}], "cpu": 82}


def test_without_a_named_part_it_stays_the_plain_line(monkeypatch):
    # the fans hold full speed a few degrees under the limit before letting go
    (item,) = _hot(monkeypatch, {"disks": [{"name": "sdb", "temp": 53}], "cpu": {"temp": 77}})
    assert "hot" not in item
    (item,) = _hot(monkeypatch, None)
    assert "hot" not in item


def test_nothing_when_nothing_is_too_hot(monkeypatch):
    assert _hot(monkeypatch, {"disks": [{"name": "sdb", "temp": 60}]}, active=False) == []


def test_only_the_processor(monkeypatch):
    (item,) = _hot(monkeypatch, {"disks": [], "cpu": {"temp": 80}})
    assert item["hot"] == {"drives": [], "cpu": 80}
