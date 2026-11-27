import time

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from backend.auth import require_scope
from backend.state import Z_STATE

router = APIRouter(tags=["Metrics"])


def _safe_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _label(text: str) -> str:
    """A label value as Prometheus wants it: a pool may be named with a quote or a backslash."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _add_disks(add_gauge, disks: list[dict]) -> None:
    """Each drive's temperature, health, and whether it sleeps. (This page once offered
    kiboto_disk_io_ticks from a field the drive's record never had, so it was never sent.)"""
    from backend.services.pool_numbers import drive_level

    for d in disks:
        labels = {"device": _label(d.get("name") or d.get("dev") or ""), "role": _label(d.get("role", "data"))}
        add_gauge("kiboto_disk_temp_celsius", "Disk Temperature", d.get("temp"), labels)
        add_gauge("kiboto_disk_io_ticks", "Disk IO Ticks", d.get("io_ticks"), labels)
        add_gauge("kiboto_disk_health", "Drive health: 0 good, 1 showing wear, 2 failing", drive_level(d), labels)
        if "standby" in d:
            add_gauge("kiboto_disk_standby", "1 while the drive sleeps", int(bool(d["standby"])), labels)
        if "active" in d:
            add_gauge("kiboto_disk_active", "1 while the drive is reading or writing", int(bool(d["active"])), labels)


def _add_storage(add_gauge) -> None:
    """How full the NAS is: each pool that has a size, and all of them together."""
    from backend.services.pool_numbers import pool_numbers, totals

    pools = pool_numbers()
    for p in pools:
        labels = {"pool": _label(p["name"]), "type": _label(p["type"])}
        add_gauge("kiboto_pool_total_bytes", "Size of a storage pool", p["total"], labels)
        add_gauge("kiboto_pool_used_bytes", "Space used in a storage pool", p["used"], labels)
        add_gauge("kiboto_pool_free_bytes", "Space free in a storage pool", p["free"], labels)
        add_gauge("kiboto_pool_usage_percent", "How full a storage pool is", p["pct"], labels)
        add_gauge(
            "kiboto_pool_healthy", "1 when the pool is healthy, 0 when it needs a look", int(p["healthy"]), labels
        )
    whole = totals(pools)
    if whole:
        add_gauge("kiboto_storage_total_bytes", "Size of all storage pools", whole["total"])
        add_gauge("kiboto_storage_used_bytes", "Space used in all storage pools", whole["used"])
        add_gauge("kiboto_storage_free_bytes", "Space free in all storage pools", whole["free"])
        add_gauge("kiboto_storage_usage_percent", "How full the storage is", whole["pct"])


def _add_energy(add_gauge) -> None:
    """The electricity totals of the Power page, once a UPS has been measured."""
    from backend.services import energy_use

    try:
        seen = energy_use.summary()
    except (OSError, ValueError, TypeError):
        return
    if not seen.get("measuring"):
        return
    add_gauge("kiboto_energy_today_kwh", "Electricity used today", seen.get("today_kwh"))
    add_gauge("kiboto_energy_7d_kwh", "Electricity used in the last 7 days", seen.get("week_kwh"))
    add_gauge("kiboto_energy_30d_kwh", "Electricity used in the last 30 days", seen.get("month_kwh"))
    add_gauge("kiboto_energy_average_watts", "Average power over the measured time", seen.get("avg_watts"))
    add_gauge("kiboto_energy_total_kwh", "All the electricity measured so far (only grows)", seen.get("total_kwh"))


@router.get("/metrics", response_class=PlainTextResponse, dependencies=[Depends(require_scope("system:view"))])
def prometheus_metrics():
    """Prometheus exposition format for Kiboto telemetry."""
    from backend import spawns
    from backend.request_metrics import REQUEST_METRICS

    if not Z_STATE.cached_stats:
        return "# Kiboto metrics not ready yet\n" + REQUEST_METRICS.prometheus() + spawns.prometheus()

    stats = Z_STATE.cached_stats
    lines = []

    def add_gauge(name, help_text, val, labels=None):
        if val is None:
            return
        label_str = ""
        if labels:
            parts = [f'{k}="{v}"' for k, v in labels.items()]
            label_str = "{" + ",".join(parts) + "}"

        if name not in lines_by_metric:
            lines_by_metric[name] = [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
        lines_by_metric[name].append(f"{name}{label_str} {_safe_float(val)}")

    lines_by_metric = {}

    # CPU
    cpu = stats.get("cpu", {})
    add_gauge("kiboto_cpu_temp_celsius", "CPU Temperature", cpu.get("temp"))
    add_gauge("kiboto_cpu_usage_percent", "CPU Usage", cpu.get("util") if "util" in cpu else cpu.get("usage"))
    add_gauge("kiboto_cpu_power_watts", "CPU Power Consumption", cpu.get("power_w"))

    # RAM
    mem = stats.get("mem", {})
    total_b = (mem["total_gb"] * 1024 * 1024 * 1024) if "total_gb" in mem else mem.get("total")
    used_b = (mem["used_gb"] * 1024 * 1024 * 1024) if "used_gb" in mem else mem.get("used")
    free_b = (total_b - used_b) if (total_b is not None and used_b is not None) else mem.get("free")
    pct = mem.get("pct") if "pct" in mem else mem.get("percent")

    add_gauge("kiboto_memory_total_bytes", "Total RAM", total_b)
    add_gauge("kiboto_memory_used_bytes", "Used RAM", used_b)
    add_gauge("kiboto_memory_free_bytes", "Free RAM", free_b)
    add_gauge("kiboto_memory_usage_percent", "RAM Usage", pct)
    from backend.services import memory_watch

    own = memory_watch.current()
    add_gauge("kiboto_backend_resident_bytes", "Resident memory of the Kiboto backend process", own["rss_kb"] * 1024)
    add_gauge("kiboto_backend_uptime_seconds", "Seconds since the backend process started", own["uptime_s"])

    # Network
    net = stats.get("net", {})
    add_gauge("kiboto_network_rx_bytes", "Network Bytes Received", net.get("rx_bytes"))
    add_gauge("kiboto_network_tx_bytes", "Network Bytes Transmitted", net.get("tx_bytes"))
    add_gauge(
        "kiboto_network_combined_rx_bytes_sec",
        "Network Combined Rx Rate (Bytes/sec)",
        net.get("rx_bytes_sec") or net.get("rx_rate"),
    )
    add_gauge(
        "kiboto_network_combined_tx_bytes_sec",
        "Network Combined Tx Rate (Bytes/sec)",
        net.get("tx_bytes_sec") or net.get("tx_rate"),
    )
    for if_name, if_data in net.get("interfaces", {}).items():
        if_labels = {"interface": if_name}
        add_gauge("kiboto_network_interface_rx_bytes", "Interface Rx Bytes", if_data.get("rx_bytes"), if_labels)
        add_gauge("kiboto_network_interface_tx_bytes", "Interface Tx Bytes", if_data.get("tx_bytes"), if_labels)
        add_gauge(
            "kiboto_network_interface_rx_bytes_sec",
            "Interface Rx Rate",
            if_data.get("rx_bytes_sec") or if_data.get("rx_rate"),
            if_labels,
        )
        add_gauge(
            "kiboto_network_interface_tx_bytes_sec",
            "Interface Tx Rate",
            if_data.get("tx_bytes_sec") or if_data.get("tx_rate"),
            if_labels,
        )

    # Disks
    _add_disks(add_gauge, stats.get("disks") or [])

    # Fans
    fans = stats.get("fans", [])
    for i, f in enumerate(fans):
        labels = {"fan_id": str(i)}
        add_gauge("kiboto_fan_rpm", "Fan RPM", f, labels)

    # UPS
    ups = stats.get("ups", {})
    if ups.get("available"):
        add_gauge("kiboto_ups_charge_percent", "UPS Battery Charge", ups.get("battery_charge_pct"))
        add_gauge("kiboto_ups_time_left_minutes", "UPS Time Left", ups.get("time_left_min"))
        add_gauge("kiboto_ups_load_percent", "UPS Load", ups.get("load_pct"))
        add_gauge("kiboto_ups_line_volts", "UPS Line Voltage", ups.get("line_volts"))
        add_gauge("kiboto_ups_battery_volts", "UPS Battery Voltage", ups.get("battery_volts"))
        add_gauge("kiboto_ups_power_watts", "Power drawn through the UPS", ups.get("power_watts"))
    _add_energy(add_gauge)
    _add_storage(add_gauge)

    # Unraid
    unraid = stats.get("unraid", {})
    if unraid.get("available"):
        add_gauge("kiboto_unraid_disk_count", "Unraid Disk Count", unraid.get("disk_count"))
        add_gauge(
            "kiboto_unraid_parity_status",
            "Unraid Parity Checks (0=Idle, 1=Checking)",
            1 if unraid.get("parity_check_running") else 0,
        )

    out = []
    for _metric_name, metric_lines in lines_by_metric.items():
        out.extend(metric_lines)

    return "\n".join(out) + "\n" + REQUEST_METRICS.prometheus() + spawns.prometheus()


@router.get("/metrics/network-topology", dependencies=[Depends(require_scope("system:view"))])
async def metrics_network_topology():
    """Network topology metrics and switch status."""
    import asyncio

    from backend.hardware.network import get_network_topology

    return await asyncio.to_thread(get_network_topology)


class RouteMetrics(BaseModel):
    method: str
    route: str
    requests: int
    server_errors: int
    client_errors: int
    avg_ms: float | None = None
    p50_ms_max: float | None = None
    p95_ms_max: float | None = None


class RequestMetricsOut(BaseModel):
    routes: list[RouteMetrics]


@router.get("/metrics/requests", response_model=RequestMetricsOut, dependencies=[Depends(require_scope("system:view"))])
def request_metrics_summary(top: int = 25):
    """The busiest API routes: requests, errors and latency (ARCH-10)."""
    from backend.request_metrics import REQUEST_METRICS

    return {"routes": REQUEST_METRICS.summary(top=max(1, min(200, top)))}


class MemorySample(BaseModel):
    ts: int
    pid: int
    uptime_s: int
    rss_kb: int
    anon_kb: int
    file_kb: int
    threads: int


class MemoryRun(BaseModel):
    pid: int
    from_ts: int
    to_ts: int
    uptime_s: int
    rss_kb_first: int
    rss_kb_last: int
    kb_per_hour: int | None = None


class MemoryOut(BaseModel):
    now: MemorySample
    samples: list[MemorySample]
    runs: list[MemoryRun]


class ObjectCount(BaseModel):
    type: str
    count: int


class Allocation(BaseModel):
    where: str
    kb: int
    blocks: int


class MemoryBreakdownOut(BaseModel):
    now: MemorySample
    objects: list[ObjectCount]
    tracing: bool
    allocations: list[Allocation]


class TracingIn(BaseModel):
    on: bool


class TracingOut(BaseModel):
    tracing: bool


@router.get("/metrics/memory", response_model=MemoryOut, dependencies=[Depends(require_scope("system:view"))])
def memory_history(hours: int = 168):
    """The backend's resident memory every 10 minutes, and its growth per run between restarts."""
    from backend.services import memory_watch

    rows = memory_watch.history(hours)
    return {"now": memory_watch.current(), "samples": rows, "runs": memory_watch.growth(rows)}


@router.get(
    "/metrics/memory/breakdown",
    response_model=MemoryBreakdownOut,
    dependencies=[Depends(require_scope("system:config"))],
)
def memory_breakdown(top: int = 25):
    """What the backend holds now: Python objects by type and, while tracing, the lines that allocated most."""
    from backend.services import memory_watch

    return memory_watch.breakdown(max(1, min(100, top)))


@router.post(
    "/metrics/memory/tracing", response_model=TracingOut, dependencies=[Depends(require_scope("system:config"))]
)
def memory_tracing(body: TracingIn):
    """Turns allocation tracing on or off (it costs memory and time while on)."""
    from backend.services import memory_watch

    return {"tracing": memory_watch.set_tracing(body.on)}
