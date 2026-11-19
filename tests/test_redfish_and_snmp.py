"""
Tests for the DMTF Redfish REST API (the SNMP routes were removed in SET-01: no agent existed).
"""

import pytest

from backend.state import Z_STATE


def test_redfish_service_root(client, auth_headers):
    res = client.get("/redfish/v1/", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["RedfishVersion"] == "1.15.0"
    assert data["Id"] == "RootService"
    assert "Systems" in data
    assert "Chassis" in data
    assert "Storage" in data


SEEDED_STATS = {
    "chassis": "d6u",
    "cpu": {"temp": 42.5, "util": 15.0},
    "disks": [
        {"dev": "sda", "name": "sda", "temp": 35.0, "standby": False, "size_bytes": 4000000000000},
        {"dev": "nvme0n1", "name": "nvme0n1", "temp": 40.0, "standby": False, "size_bytes": 1000000000000},
    ],
    "fans": [1200, 850],
    "mem": {"total_gb": 32.0, "used_gb": 8.0, "pct": 25.0},
}


@pytest.fixture(autouse=True)
def _seeded_stats(monkeypatch, tmp_path):
    """Each test sees the same stats, whatever ran before it (ARC-13); Redfish is turned on."""
    import copy

    from backend.services import redfish_access

    monkeypatch.setattr(redfish_access, "SETTINGS_FILE", str(tmp_path / "redfish.json"))
    redfish_access.set_enabled(True)

    monkeypatch.setattr(Z_STATE, "cached_stats", copy.deepcopy(SEEDED_STATS))
    # the kernel's drive table of the machine running the tests must not show through
    from backend.api import redfish

    monkeypatch.setattr(redfish, "HOST_SYS", str(tmp_path / "sys"))
    monkeypatch.setattr(redfish, "_SIZES", {})


def test_redfish_chassis_and_thermal(client, auth_headers):
    # Seed cached stats
    Z_STATE.cached_stats = {
        "chassis": "d6u",
        "cpu": {"temp": 42.5, "util": 15.0},
        "disks": [
            {"dev": "sda", "name": "sda", "temp": 35.0, "standby": False, "size_bytes": 4000000000000},
            {"dev": "nvme0n1", "name": "nvme0n1", "temp": 40.0, "standby": False, "size_bytes": 1000000000000},
        ],
        "fans": [1200, 850],
        "mem": {"total_gb": 32.0, "used_gb": 8.0, "pct": 25.0},
    }

    # 1. Chassis/1
    res = client.get("/redfish/v1/Chassis/1", headers=auth_headers)
    assert res.status_code == 200
    chassis = res.json()
    assert chassis["Id"] == "1"
    assert chassis["PowerState"] == "On"
    assert chassis["ChassisType"] == "RackMount"

    # 2. Chassis/1/Thermal
    res = client.get("/redfish/v1/Chassis/1/Thermal", headers=auth_headers)
    assert res.status_code == 200
    thermal = res.json()
    assert "Temperatures" in thermal
    assert "Fans" in thermal

    # Find CPU temp
    cpu_sensor = next((s for s in thermal["Temperatures"] if s["MemberId"] == "CPU"), None)
    assert cpu_sensor is not None
    assert cpu_sensor["ReadingCelsius"] == 42.5

    # Check Fans
    assert len(thermal["Fans"]) == 2
    assert thermal["Fans"][0]["Reading"] == 1200


def test_redfish_systems_and_storage(client, auth_headers):
    # 1. Systems/1
    res = client.get("/redfish/v1/Systems/1", headers=auth_headers)
    assert res.status_code == 200
    sys_data = res.json()
    assert sys_data["Id"] == "1"
    assert sys_data["PowerState"] == "On"
    assert "MemorySummary" in sys_data

    # 2. Storage/1
    res = client.get("/redfish/v1/Storage/1", headers=auth_headers)
    assert res.status_code == 200
    storage = res.json()
    assert "Drives" in storage

    # 3. Individual Drive
    res = client.get("/redfish/v1/Storage/1/Drives/sda", headers=auth_headers)
    assert res.status_code == 200
    drive = res.json()
    assert drive["Id"] == "sda"
    assert drive["MediaType"] == "HDD"
    assert drive["Protocol"] == "SATA"


def test_a_drive_page_reads_the_live_record(client, auth_headers, tmp_path, monkeypatch):
    """The record the collector really makes has no size_bytes and no smart_fail: every drive was
    0 bytes and "OK", a failing one too (found 19 Nov 2026 by reading both sides)."""
    for dev, sectors, rotational in (("sda", "7814037168", "1"), ("sdb", "1953525168", "0")):
        d = tmp_path / "sys" / "block" / dev / "queue"
        d.mkdir(parents=True)
        (d.parent / "size").write_text(sectors + "\n")
        (d / "rotational").write_text(rotational + "\n")
    live = {"temp": 35, "role": "data", "risk": "low", "standby": False, "active": False, "is_nvme": False}
    monkeypatch.setattr(
        Z_STATE,
        "cached_stats",
        {
            "cpu": {"model": "Intel N100", "temp": 40},
            "disks": [
                {**live, "name": "sda", "dev": "sda", "health": "crit"},
                {**live, "name": "sdb", "dev": "sdb", "health": "warn"},
                {**live, "name": "sdc", "dev": "sdc", "health": "unknown"},
                {**live, "name": "sdd", "dev": "sdd", "health": "standby", "standby": True},
                {**live, "name": "nvme0n1", "dev": "nvme0n1", "health": "ok", "is_nvme": True},
            ],
        },
    )

    def drive(dev):
        res = client.get(f"/redfish/v1/Storage/1/Drives/{dev}", headers=auth_headers)
        assert res.status_code == 200, res.text
        return res.json()

    sda, sdb, sdc, sdd = drive("sda"), drive("sdb"), drive("sdc"), drive("sdd")
    assert (sda["CapacityBytes"], sda["MediaType"], sda["Status"]["Health"]) == (7814037168 * 512, "HDD", "Critical")
    assert (sdb["CapacityBytes"], sdb["MediaType"], sdb["Status"]["Health"]) == (1953525168 * 512, "SSD", "Warning")
    assert sdc["CapacityBytes"] is None and sdc["Status"]["Health"] is None  # not known is not 0 and not OK
    assert sdd["Status"] == {"State": "StandbyOffline", "Health": "OK"}
    assert drive("nvme0n1")["MediaType"] == "SSD" and drive("nvme0n1")["Status"]["Health"] == "OK"
    array = client.get("/redfish/v1/Storage/1", headers=auth_headers).json()
    assert array["Status"]["Health"] == "Critical"  # its worst drive
    system = client.get("/redfish/v1/Systems/1", headers=auth_headers).json()
    assert system["MemorySummary"]["TotalSystemMemoryGiB"] is None  # no 32 GiB made up
    assert system["ProcessorSummary"]["Model"] == "Intel N100"


def test_redfish_drive_helpers():
    from backend.api import redfish

    assert redfish._worst(["OK", None, "Warning"]) == "Warning" and redfish._worst([]) == "OK"
    assert redfish._drive_health({"smart_fail": True}) == "Critical" and redfish._drive_health({}) == "OK"
    assert redfish._sys_block("../etc/passwd", "size") is None and redfish._sys_block("", "size") is None
    assert redfish._capacity({"size_bytes": 5}) == 5 and redfish._capacity({"dev": "nope", "size_bytes": 0}) is None
