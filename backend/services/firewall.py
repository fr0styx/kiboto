"""Host firewall (audit A13; off by default). Kiboto keeps one nftables table, "inet kiboto".

When it is on, the home network reaches everything on this machine, and the outside reaches only
the services the owner ticks. So nothing at home is shut out by a list that is missing a port, and
this page stays reachable from home whatever is ticked. The home network is the private address
ranges, Tailscale's range, and the IPv6 network the machine is on. A port Docker publishes for an
app is forwarded to its container, not received by the machine, so the input rules never see it:
a second chain drops such a connection when it comes from outside, unless "apps" is ticked.

Kiboto manages the firewall on a machine it runs (Kiboto OS), through the host door, and on a
system that says so with KIBOTO_OWNS_FIREWALL=1. In a container on Unraid or TrueNAS the host's
own firewall applies; the page says so and the switch stays off."""

from __future__ import annotations

import ipaddress
import os
import shutil
import subprocess
import time
from typing import Any

from backend import door
from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, read_json

STATE_FILE = os.path.join(DATA_DIR, "firewall.json")
TABLE = "kiboto"
LAN4 = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")
LAN6 = ("fc00::/7", "fe80::/10")
IF_INET6 = "/proc/net/if_inet6"
NFT_PLACES = ("/usr/sbin/nft", "/sbin/nft")  # a service's PATH may leave the sbin folders out
SERVICE_IDS = ("web", "ssh", "smb", "nfs", "webdav", "sftp", "tailscale", "apps")  # apps: no ports of its own
CHECK_EVERY_SECS = 900

_loaded = {"text": ""}  # the rules this process last loaded: a change of the home network loads them again


def services() -> dict[str, tuple[tuple[int, ...], tuple[int, ...]]]:
    """id -> (tcp ports, udp ports) of what can be opened to the outside. "web" is this page, on its
    plain port and on its HTTPS port."""
    from backend.config import SETTINGS

    web = tuple(
        sorted({int(getattr(SETTINGS, "port", 8082) or 8082), int(getattr(SETTINGS, "https_port", 8443) or 8443)})
    )
    return {
        "web": (web, ()),
        "ssh": ((22,), ()),
        "smb": ((139, 445), ()),
        "nfs": ((111, 2049), (111, 2049)),
        "webdav": ((8084,), ()),
        "sftp": ((2222,), ()),
        "tailscale": ((), (41641,)),
    }


def cleaned(st: dict[str, Any]) -> dict[str, Any]:
    """Only what the page offers, from whatever was sent: on or off, and what the outside reaches."""
    raw = st.get("outside")
    outside: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return {"enabled": st.get("enabled") is True, "outside": {k: outside.get(k) is True for k in SERVICE_IDS}}


def state() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    data = data if isinstance(data, dict) else {}
    if "outside" not in data and "services" in data:
        # Kept by a version before: the ticked services were open to the home network only, or to
        # every address. Only the second opened anything to the outside, and this page with it.
        everywhere = data.get("allow_from") == "anywhere"
        kept = data.get("services")
        old: dict[str, Any] = kept if isinstance(kept, dict) else {}
        # (apps' published ports were never closed by that version, so "every address" keeps them)
        data = {
            "enabled": data.get("enabled"),
            "outside": {k: everywhere and (k in ("web", "apps") or old.get(k) is True) for k in SERVICE_IDS},
        }
    return cleaned(data)


def onlink6() -> tuple[str, ...]:
    """The public IPv6 networks this machine has an address on. Devices at home use such addresses
    too, so they are part of the home network; a private or link-local one is in LAN6 already."""
    try:
        with open(IF_INET6, encoding="ascii") as f:
            lines = f.read().splitlines()
    except OSError:
        return ()
    found = set()
    for line in lines:
        parts = line.split()
        try:
            addr, length, scope = ipaddress.IPv6Address(int(parts[0], 16)), int(parts[2], 16), int(parts[3], 16)
        except (IndexError, ValueError):
            continue
        if scope == 0 and 48 <= length <= 64 and addr.is_global:
            found.add(str(ipaddress.IPv6Network((int(addr), length), strict=False)))
    return tuple(sorted(found))


def home(onlink: tuple[str, ...] | None = None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The home network: (IPv4 ranges, IPv6 ranges)."""
    return LAN4, (*LAN6, *(onlink6() if onlink is None else onlink))


def is_home(address: str, onlink: tuple[str, ...] | None = None) -> bool:
    """Whether a connection from this address is let in whatever is ticked. An address that cannot
    be read counts as home: it is used to warn, never to open anything."""
    try:
        ip = ipaddress.ip_address(str(address).split("%")[0])
    except ValueError:
        return True
    mapped = getattr(ip, "ipv4_mapped", None)
    ip = mapped or ip
    if ip.is_loopback:
        return True
    v4, v6 = home(onlink)
    return any(ip in ipaddress.ip_network(net) for net in (v4 if ip.version == 4 else v6))


def _owns() -> bool:
    from backend import runtime
    from backend.config import SETTINGS

    return runtime.managed_host() or bool(getattr(SETTINGS, "owns_firewall", False))


def _nft() -> str:
    return shutil.which("nft") or next((p for p in NFT_PLACES if os.path.exists(p)), "")


def capability() -> tuple[bool, str]:
    """(possible, why not) for managing the host's firewall from here."""
    if not _owns():
        return False, "host"
    if not _nft():
        return False, "no_nft"
    if door.available():  # the host door loads the rules: this process needs no permission of its own
        return True, ""
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


def ruleset(st: dict[str, Any], onlink: tuple[str, ...] | None = None) -> str:
    """The nftables script for these settings. Replaces Kiboto's own table only."""
    v4, v6 = home(onlink)
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
        f"    ip saddr {_set(v4)} accept  # the home network",
        f"    ip6 saddr {_set(v6)} accept  # the home network",
    ]
    outside = st.get("outside") or {}
    for sid, (tcp, udp) in services().items():
        if outside.get(sid) is not True:
            continue
        for proto, ports in (("tcp", tcp), ("udp", udp)):
            if ports:
                lines.append(f"    {proto} dport {_set(ports)} accept  # {sid}, from outside")
    lines.append("  }")
    if outside.get("apps") is not True:
        # what Docker publishes for an app reaches its container through the forward hook, after its
        # address was rewritten (dnat): only those connections, and only from outside, end here
        lines += [
            "  chain forward {",
            "    type filter hook forward priority -1; policy accept;",
            "    ct state established,related accept",
            f"    ct status dnat ip saddr != {_set(v4)} drop  # an app's published port, from outside",
            f"    ct status dnat ip6 saddr != {_set(v6)} drop  # an app's published port, from outside",
            "  }",
        ]
    lines.append("}")
    return "\n".join(lines) + "\n"


def apply(st: dict[str, Any], run=subprocess.run) -> None:
    """Loads the table (on) or removes it (off), through the host door where it runs (ADR 0006).
    Only called where capability() allows."""
    if run is subprocess.run:
        door.via("firewall.apply", _load, st=st)
    else:
        _load(st, run)
    _loaded["text"] = ruleset(st) if st["enabled"] else ""


def _load(st: dict[str, Any], run=subprocess.run) -> None:
    script = ruleset(st) if st["enabled"] else f"table inet {TABLE}\ndelete table inet {TABLE}\n"
    res = run([_nft() or "nft", "-f", "-"], input=script, text=True, capture_output=True, timeout=15)
    if res.returncode != 0:
        raise RuntimeError("The firewall rules could not be loaded: " + (res.stderr or "").strip()[:300])


def save(enabled: bool, outside: dict[str, bool], run=subprocess.run, asked_from: str = "") -> dict[str, Any]:
    """Keeps the settings and loads them. `asked_from` is the address the request came from: turning
    the firewall on from outside the home network without this page ticked would shut the asker out."""
    from backend.errors import SaidError

    possible, _why = capability()
    if enabled and not possible:
        raise ValueError("Kiboto can't manage this NAS's firewall from here.")
    wanted = {k: v for k, v in (outside or {}).items() if k in SERVICE_IDS}
    st = cleaned({"enabled": enabled, "outside": {**state()["outside"], **wanted}})
    if st["enabled"] and asked_from and not st["outside"]["web"] and not is_home(asked_from):
        raise SaidError(
            'You are connected from outside your home network. Tick "Kiboto (this page)" first, '
            "or you would shut yourself out.",
            "fw_outside_self",
        )
    if possible:
        apply(st, run=run)
    atomic_write_json(STATE_FILE, st)
    return st


def reapply_at_start(run=subprocess.run) -> None:
    """After a restart the table is gone; load it again when the firewall is on."""
    st = state()
    if st["enabled"] and capability()[0]:
        apply(st, run=run)


def keep_current(run=subprocess.run) -> bool:
    """Loads the rules again when they would differ from the loaded ones: an internet provider
    changes a home's IPv6 network now and then, and the old one must not stay "home"."""
    st = state()
    if not st["enabled"] or not capability()[0] or ruleset(st) == _loaded["text"]:
        return False
    apply(st, run=run)
    return True


def watch(sleep=time.sleep, rounds: int | None = None) -> None:
    """The loop behind keep_current, for a thread of its own."""
    from backend.config import logger

    done = 0
    while rounds is None or done < rounds:
        sleep(CHECK_EVERY_SECS)
        done += 1
        try:
            if keep_current():
                logger.info("[Firewall] The home network changed: the rules were loaded again")
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("[Firewall] The rules could not be loaded again: %s", e)
