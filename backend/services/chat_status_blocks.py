"""What the model is told about the NAS's own state: one short block per status tool.

Each block is written from the fields its tool really returns, and a test runs the tool and
reads the block: the storage block once read fields the tool never sent and told the model
that every pool had 0.0 GB, the disk block named no disk, and the fan block was empty."""

from collections.abc import Callable
from typing import Any


def _pct(v: Any) -> str:
    return "unknown" if v is None else f"{v}%"


def _first(tr: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if tr.get(k) is not None:
            return tr[k]
    return None


def span(seconds: float) -> str:
    """A running time a person would say: "3 days 17 hours", "5 hours 12 minutes", "40 minutes"."""
    mins = int(seconds // 60)
    days, hours, minutes = mins // 1440, (mins % 1440) // 60, mins % 60
    parts = [(days, "day"), (hours, "hour")] if days else [(hours, "hour"), (minutes, "minute")]
    said = [f"{n} {word}{'' if n == 1 else 's'}" for n, word in parts if n]
    return " ".join(said) or "less than a minute"


def size(item: dict[str, Any], what: str) -> str:
    """A pool's size as the tool sent it: TiB from one TiB up, GB below (both count in 1024s)."""
    tib, gb = item.get(f"{what}_tib"), item.get(f"{what}_gb")
    if isinstance(tib, (int, float)) and tib >= 1:
        return f"{tib} TiB"
    if isinstance(gb, (int, float)):
        return f"{gb:.1f} GB"
    return f"{round(tib * 1024, 1)} GB" if isinstance(tib, (int, float)) else "size unknown"


def cpu_said(tr: dict[str, Any]) -> str:
    """The CPU's load and temperature in a few words, without a number that was not read."""
    load, temp = tr.get("cpu_load_pct"), tr.get("cpu_temp_c")
    if load is None:
        return "CPU not read yet" if temp is None else f"CPU {temp}°C"
    return f"CPU {load}%" + (f" ({temp}°C)" if temp is not None else "")


def cpu_marked(tr: dict[str, Any]) -> str:
    """The same for the answer written without a model, in its code marks."""
    load, temp = tr.get("cpu_load_pct"), tr.get("cpu_temp_c")
    if load is None:
        return "not read yet" if temp is None else f"`{temp}°C`"
    return f"`{load}%`" + (f" at `{temp}°C`" if temp is not None else "")


def electricity_marked(tr: dict[str, Any]) -> str:
    """One more line for the answer written without a model, once a UPS is measured; else nothing."""
    el = tr.get("electricity")
    if not isinstance(el, dict) or not el.get("measuring"):
        return ""
    cost = f"; a month costs about `{el['month_cost']}`" if el.get("month_cost") is not None else ""
    return (
        f"\n- **Electricity used:** `{el.get('today_kwh')} kWh` today, `{el.get('week_kwh')} kWh` in 7 days, "
        f"`{el.get('month_kwh')} kWh` in 30 days (average `{el.get('avg_watts')} W`){cost}"
    )


def storage_marked(tr: dict[str, Any]) -> str:
    """The storage section of the answer written without a model: each pool, then any damaged files."""
    lines = [
        f"  - **{p.get('name')}** ({p.get('type', 'storage')}): no size reported; it is empty or not mounted"
        if sizeless(p)
        else f"  - **{p.get('name')}** ({p.get('type', 'storage')}): `{p.get('used_gb', 0):.1f} GB` used of "
        f"`{p.get('total_gb', 0):.1f} GB` (`{p.get('used_pct', 0)}%`), `{p.get('free_gb', 0):.1f} GB` free "
        f"(Health: `{p.get('health', 'ONLINE')}`)"
        for p in tr.get("pools") or []
    ]
    for d in tr.get("damaged_files") or []:
        names = ", ".join(f"`{f}`" for f in (d.get("files") or [])[:5])
        lines.append(
            f"- **⚠️ Damaged files in {d.get('pool')}:** `{d.get('count')}`"
            + (f" ({names})" if names else "")
            + ". Restore them from a backup or a snapshot."
        )
    return "### 🗄️ NAS Storage Pools Status (0 Disk Wakeups)\n" + ("\n".join(lines) or "- No storage pools discovered.")


def sizeless(pool: dict[str, Any]) -> bool:
    """True for a pool that reports a size of nothing: an empty slot, or a pool that is not mounted."""
    sizes = [pool.get(k) for k in ("total_tib", "total_gb") if isinstance(pool.get(k), (int, float))]
    return bool(sizes) and not any(sizes)


def telemetry_block(tr: dict[str, Any]) -> str:
    cpu = tr.get("cpu") if isinstance(tr.get("cpu"), dict) else {}
    mem = tr.get("memory") if isinstance(tr.get("memory"), dict) else {}
    cpu_util = _first(tr, "cpu_load_pct") if tr.get("cpu_load_pct") is not None else (cpu or {}).get("util")
    cpu_temp = _first(tr, "cpu_temp_c") if tr.get("cpu_temp_c") is not None else (cpu or {}).get("temp")
    mem_pct = _first(tr, "ram_used_pct") if tr.get("ram_used_pct") is not None else (mem or {}).get("used_pct")
    ram_used, ram_tot = tr.get("ram_used_gb"), tr.get("ram_total_gb")
    temp_str = f", Temp: {cpu_temp}°C" if cpu_temp is not None else ""
    ram_detail = f" ({ram_used}/{ram_tot} GB)" if ram_used and ram_tot else ""
    lines = [
        "## NAS System Telemetry:",
        f"- CPU Utilization: {_pct(cpu_util)}{temp_str}",
        f"- RAM Usage: {_pct(mem_pct)}{ram_detail}",
    ]
    nas_up = tr.get("nas_uptime_seconds")
    if isinstance(nas_up, (int, float)) and nas_up > 0:
        lines.append(f"- The NAS has been up for: {span(nas_up)}")
    up = tr.get("uptime_seconds")
    if isinstance(up, (int, float)) and up > 0:
        lines.append(f"- Kiboto has been running for: {span(up)} (since it last started, not since the NAS did)")
    accel = tr.get("hardware_accelerator")
    if isinstance(accel, dict) and accel.get("device_label"):
        lines.append(f"- AI runs on: {accel['device_label']}")
    el = tr.get("electricity")
    if isinstance(el, dict) and el.get("measuring"):
        line = (
            f"- Electricity used (measured at the UPS): {el.get('today_kwh')} kWh today, "
            f"{el.get('week_kwh')} kWh in the last 7 days, {el.get('month_kwh')} kWh in the last 30 days, "
            f"{el.get('avg_watts')} W on average"
        )
        if el.get("month_cost") is not None:
            line += f"; a month costs about {el['month_cost']} at the price set in Settings, Power"
        lines.append(line)
    return "\n".join(lines)


# A drive's health word, as the sentence about the drive ends. A sleeping drive (standby) and a
# drive with no word say nothing: its state already tells that it sleeps.
HEALTH_SAID = {
    "ok": ", health good",
    "warn": ", health: WARNING, it shows signs of wear",
    "crit": ", health: CRITICAL, it is failing",
    "unknown": ", health not read lately",
}


def disks_block(tr: dict[str, Any]) -> str:
    lines = ["## Storage Disks Status:"]
    if tr.get("running_disks_count") is not None or tr.get("sleeping_disks_count") is not None:
        lines.append(
            f"- {tr.get('running_disks_count', 0)} awake, {tr.get('sleeping_disks_count', 0)} asleep "
            "(no sleeping drive was woken to read this)"
        )
    worn, failing, read = [], [], 0
    for d in (tr.get("disks") or [])[:12]:
        name = _first(d, "device", "name") or "Disk"
        temp = _first(d, "temp_c", "temp")
        state = _first(d, "state", "power_state") or "active"
        word = str(d.get("health") or "").lower()
        health = HEALTH_SAID.get(word, "")
        read += word in ("ok", "warn", "crit")
        if word == "warn":
            worn.append(name)
        elif word == "crit":
            failing.append(name)
        lines.append(f"- {name}: {state}, " + (f"{temp}°C" if temp is not None else "temperature not read") + health)
    if failing:
        lines.append(f"- Failing, replace soon: {', '.join(failing)}")
    if worn:
        lines.append(f"- Showing wear, keep an eye on: {', '.join(worn)}")
    if read and not failing and not worn:
        lines.append("- Every drive whose health was read reports good health.")
    return "\n".join(lines)


def fans_block(tr: dict[str, Any]) -> str:
    lines = ["## Cooling Fans Status:"]
    profile = tr.get("profile")
    if profile:
        fixed = (
            f" (held at {tr.get('manual_pct')}%)" if profile == "manual" and tr.get("manual_pct") is not None else ""
        )
        lines.append(f"- Fan profile: {profile}{fixed}")
    if tr.get("temp_min_c") is not None and tr.get("temp_max_c") is not None:
        lines.append(f"- Fans speed up between {tr['temp_min_c']}°C and {tr['temp_max_c']}°C")
    if tr.get("zero_rpm_enabled") is not None:
        lines.append(f"- Fans may stop when it is cool: {'yes' if tr['zero_rpm_enabled'] else 'no'}")
    sent = tr.get("pwm_channels")
    channels: dict[str, Any] = sent if isinstance(sent, dict) else {}
    for key in sorted(channels):
        raw = channels[key]
        share = f" ({round(raw * 100 / 255)}% of full speed)" if isinstance(raw, (int, float)) else ""
        lines.append(f"- {key}: drive level {raw} of 255{share}")
    for idx, f in enumerate(tr.get("fans") or [], start=1):
        lines.append(f"- Fan {f.get('zone', idx)}: {f.get('rpm', 'N/A')} RPM ({f.get('pwm_pct', 0)}%)")
    return "\n".join(lines)


def storage_block(tr: dict[str, Any]) -> str:
    pools = tr.get("pools") or []
    lines = ["## NAS Storage Pools Status:"]
    for p in pools[:6]:
        kind = _first(p, "fs_type", "type") or "storage"
        health = _first(p, "health", "status") or "ONLINE"
        if sizeless(p):
            # a pool with no size is empty or not mounted: its "healthy" says nothing, so it is not repeated
            lines.append(f"- Pool '{p.get('name')}': no size reported; it is empty or not mounted (Type: {kind})")
            continue
        lines.append(
            f"- Pool '{p.get('name')}': {health} ({p.get('used_pct', 0)}% used of {size(p, 'total')}, "
            f"Free: {size(p, 'free')}, Type: {kind})"
        )
    if not pools:
        lines.append("- No storage pools reported.")
    elif tr.get("total_tib") is not None and tr.get("free_tib") is not None:
        lines.append(f"- All pools together: {size(tr, 'free')} free of {size(tr, 'total')}")
    damaged = tr.get("damaged_files")
    for d in damaged or []:
        names = ", ".join(str(f) for f in (d.get("files") or [])[:5])
        more = int(d.get("count") or 0) - min(5, len(d.get("files") or []))
        lines.append(
            f"- Damaged files in pool '{d.get('pool')}': {d.get('count')}"
            + (f" ({names}{f', and {more} more' if more > 0 else ''})" if names else "")
            + ". They should be restored from a backup or a snapshot."
        )
    if damaged == []:
        lines.append("- Damaged files: no pool reports any.")
    return "\n".join(lines)


def network_block(tr: dict[str, Any]) -> str:
    lines = ["## NAS Network Status:"]
    if tr.get("hostname"):
        lines.append(f"- Name on the network: {tr['hostname']}")
    if tr.get("ip_address"):
        lines.append(f"- IP address: {tr['ip_address']}")
    if tr.get("primary_interface"):
        lines.append(f"- Main connection: {tr['primary_interface']}")
    lines.append(f"- Default Gateway: {tr.get('default_gateway') or 'N/A'}")
    lines.append(f"- DNS: {', '.join(tr.get('dns_servers') or []) or 'N/A'}")
    ifaces = tr.get("interfaces") or []
    for iface in ifaces[:6]:
        speed, state = iface.get("speed") or "Unknown speed", iface.get("state", "up")
        if iface.get("ip"):
            line = f"- {iface.get('name')}: {iface['ip']} ({speed}, Status: {state})"
        else:  # a port inside a bond or a bridge has no address of its own
            line = f"- {iface.get('name')}: {speed}, Status: {state}"
        lines.append(line + (f", part of {iface['part_of']}" if iface.get("part_of") else ""))
    if not ifaces:
        lines.append("- No interfaces reported.")
    return "\n".join(lines)


STATUS_BLOCKS: dict[str, Callable[[dict[str, Any]], str]] = {
    "get_system_telemetry": telemetry_block,
    "get_disks_and_standby_status": disks_block,
    "get_fan_and_thermal_status": fans_block,
    "get_storage_status": storage_block,
    "get_network_status": network_block,
}
