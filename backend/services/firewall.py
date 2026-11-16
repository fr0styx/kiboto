"""Host firewall (audit A13, owner decision 16 Nov 2026: now, off by default). Kiboto keeps one
nftables table, "inet kiboto", that drops unasked-for incoming connections and lets in the services
the owner keeps on, from the home network only or from anywhere. This page's own port is always
reachable from the home network, so a setting can't lock the owner out.

Kiboto can only manage the firewall where it runs in the host's network with NET_ADMIN and nft: on
Kiboto's own OS images (which set KIBOTO_OWNS_FIREWALL=1, read through backend.settings). In a container on Unraid or TrueNAS the
host's own firewall applies; the page says so and the switch stays off."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, read_json

STATE_FILE = os.path.join(DATA_DIR, "firewall.json")
TABLE = "kiboto"
LAN4 = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")
LAN6 = ("fc00::/7", "fe80::/10")

# id -> (tcp ports, udp ports); "web" is this page and is always on from the home network
SERVICES: dict[str, tuple[tuple[int, ...], tuple[int, ...]]] = {
    "web": ((8082,), ()),
    "ssh": ((22,), ()),
    "smb": ((139, 445), ()),
    "nfs": ((111, 2049), (111, 2049)),
    "webdav": ((8084,), ()),
    "sftp": ((2222,), ()),
    "tailscale": ((), (41641,)),
    "mdns": ((), (5353,)),
}
DEFAULT_ON = {
    "web": True,
    "ssh": True,
    "smb": True,
    "nfs": False,
    "webdav": False,
    "sftp": False,
    "tailscale": True,
    "mdns": True,
}


def _defaults() -> dict[str, Any]:
    return {"enabled": False, "allow_from": "lan", "services": dict(DEFAULT_ON)}


def state() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    st = {**_defaults(), **(data if isinstance(data, dict) else {})}
    st["services"] = {k: bool((st.get("services") or {}).get(k, v)) for k, v in DEFAULT_ON.items()}
    st["services"]["web"] = True
    return st


def _owns() -> bool:
    from backend.config import SETTINGS

    return bool(getattr(SETTINGS, "owns_firewall", False))


def capability() -> tuple[bool, str]:
    """(possible, why not) for managing the host's firewall from here."""
    if not _owns():
        return False, "host"
    if not shutil.which("nft"):
        return False, "no_nft"
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            cap = next((int(line.split()[1], 16) for line in f if line.startswith("CapEff:")), 0)
    except (OSError, ValueError):
        cap = 0
    if not cap & (1 << 12):  # CAP_NET_ADMIN
        return False, "no_cap"
    return True, ""


def _set(items: tuple[Any, ...]) -> str:
    return "{ " + ", ".join(str(i) for i in items) + " }"


def ruleset(st: dict[str, Any]) -> str:
    """The nftables script for these settings. Replaces Kiboto's own table only."""
    lan = st.get("allow_from", "lan") != "anywhere"
    lines = [
        f"table inet {TABLE}",
        f"delete table inet {TABLE}",
        f"table inet {TABLE} {{",
        "  chain input {",
        "    type filter hook input priority 0; policy drop;",
        "    ct state established,related accept",
        "    ct state invalid drop",
        '    iif "lo" accept',
        "    ip protocol icmp accept",
        "    meta l4proto ipv6-icmp accept",
    ]
    for sid, (tcp, udp) in SERVICES.items():
        on = sid == "web" or st["services"].get(sid)
        if not on:
            continue
        everywhere = not lan and sid != "web"
        for proto, ports in (("tcp", tcp), ("udp", udp)):
            if not ports:
                continue
            if everywhere:
                lines.append(f"    {proto} dport {_set(ports)} accept  # {sid}")
            else:
                lines.append(f"    ip saddr {_set(LAN4)} {proto} dport {_set(ports)} accept  # {sid}")
                lines.append(f"    ip6 saddr {_set(LAN6)} {proto} dport {_set(ports)} accept  # {sid}")
        if sid == "web" and not lan:
            lines.append(f"    tcp dport {_set(tcp)} accept  # web from anywhere")
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n"


def apply(st: dict[str, Any], run=subprocess.run) -> None:
    """Loads the table (on) or removes it (off). Only called where capability() allows."""
    script = ruleset(st) if st["enabled"] else f"table inet {TABLE}\ndelete table inet {TABLE}\n"
    res = run(["nft", "-f", "-"], input=script, text=True, capture_output=True, timeout=15)
    if res.returncode != 0:
        raise RuntimeError("The firewall rules could not be loaded: " + (res.stderr or "").strip()[:300])


def save(enabled: bool, allow_from: str, services: dict[str, bool], run=subprocess.run) -> dict[str, Any]:
    if allow_from not in ("lan", "anywhere"):
        raise ValueError("Choose the home network or anywhere.")
    possible, _why = capability()
    if enabled and not possible:
        raise ValueError("Kiboto can't manage this NAS's firewall from here.")
    st = state()
    st.update({"enabled": bool(enabled), "allow_from": allow_from})
    st["services"].update({k: bool(v) for k, v in services.items() if k in SERVICES})
    st["services"]["web"] = True
    if possible:
        apply(st, run=run)
    atomic_write_json(STATE_FILE, st)
    return st


def reapply_at_start(run=subprocess.run) -> None:
    """After a restart the table is gone; load it again when the firewall is on."""
    st = state()
    if st["enabled"] and capability()[0]:
        apply(st, run=run)
