"""Kib is told the NAS's real numbers: each status tool is run and its block for the model is read.

Found on a real NAS during the 19 Nov re-audit: the storage block read fields the tool never
sent (every pool "0.0 GB"), the disk block named no disk, and the fan block was empty."""

import types

import pytest

from backend.services import ai_chat_agent, chat_nas_tools, chat_status_blocks, energy_use, pool_alerts
from backend.services.chat_synthesis import _build_structured_llm_context
from backend.state import Z_STATE

TIB = 1024**4


class _Platform:
    def __init__(self, pools, damaged=None):
        self.pools, self.damaged = pools, damaged or {}

    def list_pools(self):
        return self.pools

    def scrub_result(self, pool):
        return {"damaged": self.damaged[pool.id]} if pool.id in self.damaged else {}


def _pool(pid, name, fs, total, used):
    return types.SimpleNamespace(
        id=pid,
        name=name,
        fs_type=fs,
        status="HEALTHY",
        total_bytes=total,
        used_bytes=used,
        free_bytes=total - used,
        used_pct=round(used * 100 / total, 1),
    )


@pytest.fixture
def platform(monkeypatch):
    def use(pools, damaged=None):
        plat = _Platform(pools, damaged)
        monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda: plat)
        return plat

    return use


def test_the_model_reads_each_pools_real_size(platform):
    platform([_pool("tank", "Tank", "zfs", 8 * TIB, 2 * TIB), _pool("fast", "Fast", "btrfs", TIB // 2, TIB // 8)])
    res = chat_nas_tools.tool_get_storage_status()
    assert res["status"] == "ok" and res["damaged_files"] == []
    tank = res["pools"][0]
    # the answer written without a model reads these names
    assert (tank["type"], tank["total_gb"], tank["used_gb"], tank["free_gb"]) == ("zfs", 8192.0, 2048.0, 6144.0)
    block = _build_structured_llm_context([res])
    assert "- Pool 'Tank': HEALTHY (25.0% used of 8.0 TiB, Free: 6.0 TiB, Type: zfs)" in block
    assert "- Pool 'Fast': HEALTHY (25.0% used of 512.0 GB, Free: 384.0 GB, Type: btrfs)" in block
    assert "- All pools together: 6.38 TiB free of 8.5 TiB" in block
    assert "- Damaged files: no pool reports any." in block
    assert "0.0 GB" not in block and "Type: storage" not in block


def test_damaged_files_reach_the_model_and_the_summary(platform):
    files = [f"/tank/photos/img{i}.jpg" for i in range(8)]
    platform([_pool("tank", "Tank", "zfs", 8 * TIB, 2 * TIB)], {"tank": {"count": 8, "other": 0, "files": files}})
    res = chat_nas_tools.tool_get_storage_status()
    assert res["damaged_files"] == [{"pool": "Tank", "count": 8, "files": files[:5]}]
    assert res["summary"].endswith("; damaged files in Tank")
    block = _build_structured_llm_context([res])
    assert "- Damaged files in pool 'Tank': 8 (/tank/photos/img0.jpg" in block
    assert "img4.jpg, and 3 more). They should be restored from a backup or a snapshot." in block
    assert "no pool reports any" not in block


def test_no_pools_and_a_tool_that_failed(platform, monkeypatch):
    platform([])
    block = _build_structured_llm_context([chat_nas_tools.tool_get_storage_status()])
    assert "- No storage pools reported." in block and "All pools together" not in block

    def broken():
        raise RuntimeError("no platform")

    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", broken)
    res = chat_nas_tools.tool_get_storage_status()
    assert res["status"] == "error" and "damaged_files" not in res
    assert "Damaged files" not in _build_structured_llm_context([res])  # nothing is claimed about what was not read
    # the older field names still read (a stored result from before)
    old = {"tool": "get_storage_status", "pools": [{"name": "P", "total_gb": 100.0, "free_gb": 40.0, "used_pct": 60}]}
    assert "(60% used of 100.0 GB, Free: 40.0 GB, Type: storage)" in _build_structured_llm_context([old])
    assert chat_status_blocks.size({}, "total") == "size unknown"
    assert chat_status_blocks.size({"total_tib": 0.25}, "total") == "256.0 GB"


def test_the_disk_block_names_each_disk(monkeypatch):
    monkeypatch.setattr(chat_nas_tools, "get_running_disks_list", lambda: ["nvme0n1", "sda"])
    monkeypatch.setattr(chat_nas_tools, "get_sleeping_disks_list", lambda: ["sdb"])
    monkeypatch.setattr(Z_STATE, "cached_smart_data", {"sda": (34, "active"), "sdb": {"temp_c": 29}})
    block = _build_structured_llm_context([chat_nas_tools.tool_get_disks_and_standby_status()])
    assert "- 2 awake, 1 asleep (no sleeping drive was woken to read this)" in block
    assert "- nvme0n1: active/running, temperature not read" in block
    assert "- sda: active/running, 34°C" in block
    assert "- sdb: standby (sleeping — protected), 29°C" in block
    assert "N/A" not in block
    # the older shape still reads
    old = {"tool": "get_disks_and_standby_status", "disks": [{"name": "Bay 1", "temp": 31, "power_state": "idle"}]}
    assert "- Bay 1: idle, 31°C" in _build_structured_llm_context([old])


def test_the_fan_block_says_what_the_tool_knows(monkeypatch, tmp_path):
    state = tmp_path / "fan.json"
    state.write_text(
        '{"profile": "manual", "manual_pct": 55, "temp_min": 35, "temp_max": 48, "zero_rpm_enabled": true}'
    )
    monkeypatch.setattr(chat_nas_tools, "FAN_STATE_FILE", str(state))
    monkeypatch.setattr(Z_STATE, "fan_state_tracker", {"pwm2": {"current": 128}, "pwm1": {"current": 67}})
    block = _build_structured_llm_context([chat_nas_tools.tool_get_fan_and_thermal_status()])
    assert block.splitlines() == [
        "## Cooling Fans Status:",
        "- Fan profile: manual (held at 55%)",
        "- Fans speed up between 35°C and 48°C",
        "- Fans may stop when it is cool: yes",
        "- pwm1: drive level 67 of 255 (26% of full speed)",
        "- pwm2: drive level 128 of 255 (50% of full speed)",
    ]
    auto = {"tool": "get_fan_and_thermal_status", "profile": "auto", "zero_rpm_enabled": False}
    assert _build_structured_llm_context([auto]).splitlines()[1:] == [
        "- Fan profile: auto",
        "- Fans may stop when it is cool: no",
    ]


def test_the_network_block_gives_the_address_even_without_interfaces():
    res = {
        "tool": "get_network_status",
        "hostname": "nas",
        "ip_address": "192.0.2.10",
        "default_gateway": None,
        "dns_servers": [],
        "interfaces": [],
    }
    block = _build_structured_llm_context([res])
    assert "- Name on the network: nas" in block and "- IP address: 192.0.2.10" in block
    assert "- Default Gateway: N/A" in block and "- No interfaces reported." in block
    res["interfaces"] = [{"name": "eth0", "ip": "192.0.2.10", "speed": "2.5 Gbps", "state": "up"}]
    res["default_gateway"], res["dns_servers"] = "192.0.2.1", ["192.0.2.1", "192.0.2.2"]
    block = _build_structured_llm_context([res])
    assert "- eth0: 192.0.2.10 (2.5 Gbps, Status: up)" in block and "- DNS: 192.0.2.1, 192.0.2.2" in block
    assert "No interfaces" not in block


def test_the_network_tool_reads_the_reading_as_it_is(monkeypatch):
    """The reading has physical_interfaces and a summary; the tool once asked for other names."""
    reading = {
        "status": "ok",
        "physical_interfaces": [
            {"name": "eth0", "state": "down", "is_up": False, "speed_human": "Disconnected", "master": "bond0"},
            {"name": "eth1", "state": "up", "is_up": True, "speed_human": "10 Gbps", "master": "bond0"},
            {"name": "eth2", "state": "up", "is_up": True, "speed_human": "1 Gbps", "ip": "192.0.2.7"},
        ],
        "summary": {
            "primary_ip": "192.0.2.10",
            "default_gateway": "192.0.2.1",
            "dns_servers": ["192.0.2.1"],
            "primary_interface": "br0",
            "max_speed": "10 Gbps",
        },
    }
    monkeypatch.setattr("backend.hardware.network.get_network_topology", lambda: reading)
    monkeypatch.setattr("backend.hardware.network.read_ip", lambda: "192.0.2.10")
    res = chat_nas_tools.tool_get_network_status()
    assert res["status"] == "ok" and res["default_gateway"] == res["gateway"] == "192.0.2.1"
    assert res["dns_servers"] == ["192.0.2.1"] and res["interface_count"] == 2 and res["hostname"] is None
    assert res["summary"] == "IP: 192.0.2.10 (2 active link(s), max 10 Gbps)"
    assert _build_structured_llm_context([res]).splitlines() == [
        "## NAS Network Status:",
        "- IP address: 192.0.2.10",
        "- Main connection: br0",
        "- Default Gateway: 192.0.2.1",
        "- DNS: 192.0.2.1",
        "- eth1: 10 Gbps, Status: up, part of bond0",
        "- eth2: 192.0.2.7 (1 Gbps, Status: up)",
    ]
    # nothing known: no speed is made up, and the address falls back to the reading's own
    monkeypatch.setattr(
        "backend.hardware.network.get_network_topology", lambda: {"summary": {"primary_ip": "192.0.2.9"}}
    )
    monkeypatch.setattr("backend.hardware.network.read_ip", lambda: None)
    res = chat_nas_tools.tool_get_network_status()
    assert res["ip_address"] == "192.0.2.9" and res["summary"] == "IP: unknown (0 active link(s), max Unknown)"
    assert res["interfaces"] == [] and res["dns_servers"] == [] and res["gateway"] is None
    # the older shape of the reading still reads
    monkeypatch.setattr(
        "backend.hardware.network.get_network_topology",
        lambda: {
            "hostname": "nas",
            "gateway": "192.0.2.1",
            "dns_servers": ["192.0.2.2"],
            "interfaces": [{"name": "lan", "is_up": True, "speed_label": "2.5 Gbps", "state": "up"}],
        },
    )
    res = chat_nas_tools.tool_get_network_status()
    assert (res["hostname"], res["gateway"], res["dns_servers"]) == ("nas", "192.0.2.1", ["192.0.2.2"])
    assert res["summary"].endswith("max 2.5 Gbps)")


def test_electricity_reaches_the_model_only_once_it_is_measured(monkeypatch, tmp_path):
    monkeypatch.setattr(energy_use, "STATE_FILE", str(tmp_path / "energy.json"))
    energy_use.reset_for_tests()
    assert chat_nas_tools.tool_get_system_telemetry()["electricity"] is None
    now = 1_800_000_000.0
    for i in range(0, 3601, 60):  # an hour at 120 W
        energy_use.note(120, now=now + i)
    energy_use.set_price(0.25)
    monkeypatch.setattr(energy_use.time, "time", lambda: now + 3600)
    res = chat_nas_tools.tool_get_system_telemetry()
    el = res["electricity"]
    assert el["measuring"] and el["today_kwh"] + el["week_kwh"] > 0 and el["avg_watts"] == 120.0
    block = _build_structured_llm_context([res])
    assert "- Electricity used (measured at the UPS): " in block and "120.0 W on average" in block
    assert f"a month costs about {el['month_cost']} at the price set in Settings, Power" in block
    energy_use.set_price(None)
    assert "a month costs" not in _build_structured_llm_context([chat_nas_tools.tool_get_system_telemetry()])
    energy_use.reset_for_tests()

    def unreadable():
        raise OSError("gone")

    monkeypatch.setattr(energy_use, "summary", unreadable)
    assert chat_nas_tools.tool_get_system_telemetry()["electricity"] is None


def test_the_telemetry_block_keeps_its_first_lines_and_adds_what_is_known():
    res = {
        "tool": "get_system_telemetry",
        "cpu_load_pct": 12.4,
        "cpu_temp_c": 44,
        "ram_used_pct": 38.2,
        "ram_used_gb": 6.1,
        "ram_total_gb": 16.0,
        "uptime_seconds": 3 * 86400 + 17 * 3600 + 120,
        "hardware_accelerator": {"device_label": "Intel NPU"},
        "electricity": None,
    }
    assert _build_structured_llm_context([res]).splitlines() == [
        "## NAS System Telemetry:",
        "- CPU Utilization: 12.4%, Temp: 44°C",
        "- RAM Usage: 38.2% (6.1/16.0 GB)",
        "- Kiboto has been running for: 3 days 17 hours (since it last started, not since the NAS did)",
        "- AI runs on: Intel NPU",
    ]
    old = {"tool": "get_system_telemetry", "cpu": {"util": 7, "temp": 40}, "memory": {"used_pct": 20}}
    assert _build_structured_llm_context([old]).splitlines()[1:] == [
        "- CPU Utilization: 7%, Temp: 40°C",
        "- RAM Usage: 20%",
    ]
    bare = _build_structured_llm_context([{"tool": "get_system_telemetry"}])
    assert "CPU Utilization: unknown" in bare and "RAM Usage: unknown" in bare
    assert [chat_status_blocks.span(s) for s in (20, 60, 3600, 5 * 3600 + 12 * 60, 86400, 2 * 86400 + 3600)] == [
        "less than a minute",
        "1 minute",
        "1 hour",
        "5 hours 12 minutes",
        "1 day",
        "2 days 1 hour",
    ]


@pytest.mark.parametrize(
    "question, words, hit",
    [
        ("how much electricity does the nas use", "TELEMETRY_WORDS", True),
        ("what is the power draw right now", "TELEMETRY_WORDS", True),
        ("how many kwh this month", "TELEMETRY_WORDS", True),
        ("the power of friendship", "TELEMETRY_WORDS", False),
        ("are there any damaged files", "STORAGE_WORDS", True),
        ("which files are corrupted? any corrupted files?", "STORAGE_WORDS", True),
        ("how much free space is left", "STORAGE_WORDS", True),
        ("my phone screen is damaged", "STORAGE_WORDS", False),
    ],
)
def test_questions_reach_the_tool_that_can_answer(question, words, hit):
    assert ai_chat_agent._mentions(question, getattr(ai_chat_agent, words)) is hit


def test_the_model_is_told_what_the_two_tools_now_cover():
    said = {d["function"]["name"]: d["function"]["description"] for d in ai_chat_agent.OPENAI_TOOL_DEFINITIONS}
    assert "electricity" in said["get_system_telemetry"] and "damaged files" in said["get_storage_status"]
    assert pool_alerts.damaged_files() == [] or isinstance(pool_alerts.damaged_files(), list)


def test_no_cpu_number_is_made_up(monkeypatch):
    """Before the first reading the tool once said 8.5 % at 42 °C, and it turned a real 0 % into 8.5 %."""
    from backend.services.chat_tool_registry import _format_tool_trace_summary as said

    monkeypatch.setattr(Z_STATE, "cached_stats", {})
    res = chat_nas_tools.tool_get_system_telemetry()
    assert res["cpu_load_pct"] is None and res["cpu_temp_c"] is None
    block = _build_structured_llm_context([res])
    assert "- CPU Utilization: unknown" in block and "8.5" not in block and "42°C" not in block
    assert said(res, "get_system_telemetry").startswith("CPU not read yet, RAM ")

    monkeypatch.setattr(Z_STATE, "cached_stats", {"cpu": {"util": 0, "temp": 39}})
    res = chat_nas_tools.tool_get_system_telemetry()
    assert (res["cpu_load_pct"], res["cpu_temp_c"]) == (0, 39)  # an idle CPU is 0 %, not a default
    assert said(res, "get_system_telemetry").startswith("CPU 0% (39°C), RAM ")

    monkeypatch.setattr(Z_STATE, "cached_stats", {"cpu": 17.5, "cpu_temp": 51})
    res = chat_nas_tools.tool_get_system_telemetry()
    assert (res["cpu_load_pct"], res["cpu_temp_c"]) == (17.5, 51)
    monkeypatch.setattr(Z_STATE, "cached_stats", {"cpu_pct": 3, "cpu": {"util": 99}})
    assert chat_nas_tools.tool_get_system_telemetry()["cpu_load_pct"] == 3
    assert chat_status_blocks.cpu_said({"cpu_temp_c": 40}) == "CPU 40°C"
    assert chat_status_blocks.cpu_said({"cpu_load_pct": 5}) == "CPU 5%"
    marked = chat_status_blocks.cpu_marked
    assert [marked({}), marked({"cpu_temp_c": 40}), marked({"cpu_load_pct": 5})] == ["not read yet", "`40°C`", "`5%`"]
    assert marked({"cpu_load_pct": 5, "cpu_temp_c": 40}) == "`5%` at `40°C`"
