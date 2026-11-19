"""How full the NAS is, on the metrics page and in Home Assistant (neither carried storage before)."""

import json
import types

import pytest

from backend.api import metrics
from backend.services import home_assistant as ha
from backend.services import pool_numbers as pn
from backend.state import Z_STATE

GIB = 1024**3


def _pool(pid, name, fs, total, used, status="HEALTHY", free=None):
    return types.SimpleNamespace(
        id=pid, name=name, fs_type=fs, status=status, total_bytes=total, used_bytes=used, free_bytes=free
    )


@pytest.fixture
def pools(monkeypatch):
    def use(items):
        plat = types.SimpleNamespace(list_pools=lambda: items)
        monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda: plat)

    return use


def test_each_pool_with_a_size_and_all_together(pools):
    pools(
        [
            _pool("tank", "Tank", "zfs", 800 * GIB, 600 * GIB),
            _pool("fast", 'Fast "NVMe"', "btrfs", 200 * GIB, 50 * GIB, status="DEGRADED", free=140 * GIB),
            _pool("spare", "Spare", "auto", 0, 0),  # an empty slot is left out
            _pool("tank", "Tank again", "zfs", 100 * GIB, 0),  # the same id twice: two keys
        ]
    )
    found = pn.pool_numbers()
    assert [(p["key"], p["pct"], p["healthy"]) for p in found] == [
        ("tank", 75.0, True),
        ("fast", 25.0, False),
        ("tank_2", 0.0, True),
    ]
    assert found[0]["free"] == 200 * GIB and found[1]["free"] == 140 * GIB  # the pool's own figure when it gives one
    whole = pn.totals(found)
    assert whole == {"total": 1100 * GIB, "used": 650 * GIB, "free": 440 * GIB, "pct": 59.1}
    assert pn.totals([]) is None


def test_a_platform_that_cannot_be_read_gives_nothing(monkeypatch):
    def broken():
        raise RuntimeError("no platform")

    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", broken)
    assert pn.pool_numbers() == []
    monkeypatch.setattr(Z_STATE, "cached_stats", {"cpu": {"temp": 40}})
    assert (
        "kiboto_pool_" not in metrics.prometheus_metrics() and "kiboto_cpu_temp_celsius" in metrics.prometheus_metrics()
    )
    assert not [s for s in ha.sensors({}) if s["key"].startswith(("storage_", "pool_"))]


def test_the_metrics_page_carries_them(pools, monkeypatch):
    pools(
        [
            _pool("tank", "Tank", "zfs", 800 * GIB, 600 * GIB),
            _pool("fast", 'Fast "NVMe"', "btrfs", 200 * GIB, 50 * GIB, "DEGRADED"),
        ]
    )
    monkeypatch.setattr(Z_STATE, "cached_stats", {"cpu": {"temp": 40}})
    text = metrics.prometheus_metrics()
    assert 'kiboto_pool_usage_percent{pool="Tank",type="zfs"} 75.0' in text
    assert f'kiboto_pool_free_bytes{{pool="Tank",type="zfs"}} {float(200 * GIB)}' in text
    assert 'kiboto_pool_healthy{pool="Tank",type="zfs"} 1.0' in text
    assert 'kiboto_pool_healthy{pool="Fast \\"NVMe\\"",type="btrfs"} 0.0' in text  # the quote is escaped
    assert "kiboto_storage_usage_percent 65.0" in text and f"kiboto_storage_total_bytes {float(1000 * GIB)}" in text
    assert text.count("# TYPE kiboto_pool_usage_percent gauge") == 1


def test_home_assistant_gets_them(pools, monkeypatch):
    monkeypatch.setattr(ha, "node_id", lambda: "nas")
    monkeypatch.setattr(ha, "_electricity", lambda: None)
    pools(
        [
            _pool("tank", "Tank", "zfs", 800 * GIB, 600 * GIB),
            _pool("fast", "Fast", "btrfs", 200 * GIB, 50 * GIB, "DEGRADED"),
        ]
    )
    found = {s["key"]: s for s in ha.sensors({})}
    assert (found["storage_usage"]["value"], found["storage_free"]["value"], found["storage_free"]["unit"]) == (
        65.0,
        350.0,
        "GiB",
    )
    assert found["pool_tank_usage"]["value"] == 75.0 and found["pool_tank_free"]["device_class"] == "data_size"
    assert found["pool_tank_problem"]["value"] is False and found["pool_fast_problem"]["value"] is True
    assert (
        found["pool_fast_problem"]["component"] == "binary_sensor" and found["pool_fast_usage"]["name"] == "Fast used"
    )
    confs = {t: json.loads(p) for t, p, _ in ha.messages({}, {}) if t.endswith("/config")}
    assert confs["homeassistant/sensor/kiboto_nas/pool_tank_free/config"]["unit_of_measurement"] == "GiB"
    assert "homeassistant/binary_sensor/kiboto_nas/pool_fast_problem/config" in confs
