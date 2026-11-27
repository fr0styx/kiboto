"""Every reader of a drive's live record is fed the record the collector really makes.

Three readers were written against fields the record never had (Redfish: size_bytes and
smart_fail; the metrics page: io_ticks; Kib's disk note: name, temp, power_state), and their
tests passed because each test invented a record with those fields. Here the record comes from
the real producer, and its field names are pinned: a change to them fails this test, which
names the readers to look at."""

import time
import types

import pytest

from backend.api import metrics, redfish
from backend.hardware import disks
from backend.services import home_assistant as ha
from backend.state import Z_STATE

RECORD_FIELDS = {
    "name",
    "dev",
    "temp",
    "role",
    "health",
    "risk",
    "risk_advice",
    "standby",
    "active",
    "is_nvme",
    "is_parity",
    "parity_label",
    "usb",
}


@pytest.fixture
def records(monkeypatch, tmp_path):
    found = [{"dev": d, "role": "data"} for d in ("sda", "sdb", "sdc", "sdd", "nvme0n1")]
    monkeypatch.setattr(disks, "_discover_disks", lambda: found)
    now = time.time()
    readings = {
        "sda": (34, "ok"),
        "sdb": (41, "warn"),
        "sdc": (47, "crit"),
        "sdd": (None, "standby"),
        "nvme0n1": (39, "ok"),
    }
    monkeypatch.setattr(Z_STATE, "cached_smart_data", dict(readings))
    monkeypatch.setattr(Z_STATE, "cached_smart_time", {d: now for d in readings})
    monkeypatch.setattr(Z_STATE, "disk_risk", {})
    out = disks.read_disk_temps_and_io()
    # the kernel's drive table: sizes for two drives, one of them an SSD
    for dev, sectors, rotational in (("sda", "7814037168", "1"), ("sdb", "1953525168", "0")):
        q = tmp_path / "sys" / "block" / dev / "queue"
        q.mkdir(parents=True)
        (q.parent / "size").write_text(sectors)
        (q / "rotational").write_text(rotational)
    monkeypatch.setattr(redfish, "HOST_SYS", str(tmp_path / "sys"))
    monkeypatch.setattr(redfish, "_SIZES", {})
    return out


def test_the_record_has_exactly_these_fields(records):
    """If this fails, the record changed: check Redfish (api/redfish.py), the metrics page
    (api/metrics.py), Home Assistant (services/home_assistant.py) and the desktop, then update the set."""
    assert len(records) == 5
    for rec in records:
        assert set(rec) == RECORD_FIELDS, sorted(set(rec) ^ RECORD_FIELDS)
    by_dev = {r["dev"]: r for r in records}
    assert by_dev["nvme0n1"]["name"] == "nv0" and by_dev["sda"]["name"] == "sda"  # the short name differs for NVMe
    assert by_dev["sdd"]["standby"] is True and by_dev["sdd"]["temp"] is None


def test_redfish_reads_it(records, client, auth_headers, tmp_path, monkeypatch):
    from backend.services import redfish_access

    monkeypatch.setattr(redfish_access, "SETTINGS_FILE", str(tmp_path / "redfish.json"))
    redfish_access.set_enabled(True)
    monkeypatch.setattr(Z_STATE, "cached_stats", {"disks": records, "cpu": {"temp": 40}})

    def drive(dev):
        res = client.get(f"/redfish/v1/Storage/1/Drives/{dev}", headers=auth_headers)
        assert res.status_code == 200, res.text
        return res.json()

    assert (
        drive("sda")["Status"] == {"State": "Enabled", "Health": "OK"}
        and drive("sda")["CapacityBytes"] == 7814037168 * 512
    )
    assert drive("sdb")["Status"]["Health"] == "Warning" and drive("sdb")["MediaType"] == "SSD"
    assert drive("sdc")["Status"]["Health"] == "Critical" and drive("sdc")["CapacityBytes"] is None
    assert drive("sdd")["Status"]["State"] == "StandbyOffline"
    assert drive("nvme0n1")["Protocol"] == "NVMe"  # found by its device name, not its short name
    listed = client.get("/redfish/v1/Storage/1", headers=auth_headers).json()
    assert listed["Drives@odata.count"] == 5 and listed["Status"]["Health"] == "Critical"
    thermal = client.get("/redfish/v1/Chassis/1/Thermal", headers=auth_headers).json()
    temps = {t["MemberId"]: t for t in thermal["Temperatures"]}
    assert temps["sda"]["ReadingCelsius"] == 34.0 and temps["sdd"]["ReadingCelsius"] is None
    assert temps["sdd"]["Status"]["State"] == "StandbyOffline"


def test_the_metrics_page_reads_it(records, monkeypatch):
    plat = types.SimpleNamespace(list_pools=lambda: [])
    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda: plat)
    monkeypatch.setattr(Z_STATE, "cached_stats", {"disks": records, "cpu": {"temp": 40}})
    text = metrics.prometheus_metrics()
    assert 'kiboto_disk_temp_celsius{device="sda",role="data"} 34.0' in text
    assert 'kiboto_disk_temp_celsius{device="nv0",role="data"} 39.0' in text
    assert 'kiboto_disk_health{device="sdc",role="data"} 2.0' in text
    assert 'kiboto_disk_standby{device="sdd",role="data"} 1.0' in text
    assert 'kiboto_disk_active{device="sda",role="data"} 0.0' in text


def test_home_assistant_reads_it(records, monkeypatch):
    plat = types.SimpleNamespace(list_pools=lambda: [])
    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda: plat)
    monkeypatch.setattr(ha, "_electricity", lambda: None)
    found = {s["key"]: s["value"] for s in ha.sensors({"disks": records})}
    assert found["disk_sda_temperature"] == 34 and found["disk_nv0_temperature"] == 39
    assert "disk_sdd_temperature" not in found  # asleep: no temperature, and no made-up one
    assert found["hottest_disk_temperature"] == 47
    assert found["disk_sdb_problem"] is True and found["disk_sda_problem"] is False and found["drives_problem"] is True
