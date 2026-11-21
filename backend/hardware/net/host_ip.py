"""The host IP settings: what they are now, and changing them under the canary (validation, apply, confirm, revert).

Part of backend/hardware/network.py, split out by ARC-5."""

from typing import Any

from backend.hardware.net import common, topology
from backend.hardware.net import unraid_cfg as unraid_file
from backend.hardware.net.ipv4 import validate_ipv4 as _validate_ipv4  # noqa: F401 - kept under the old names
from backend.hardware.net.ipv4 import validate_netmask as _validate_netmask  # noqa: F401


def get_host_ip_config() -> dict[str, Any]:
    """Retrieve current host IP, netmask, gateway, DNS, and canary watchdog status."""
    topo = topology.get_network_topology()
    summary = topo.get("summary", {})
    routes = topo.get("routes", [])

    phys_names = [p["name"] for p in topo.get("physical_interfaces", [])]
    br_names = [b["name"] for b in topo.get("bridges", [])]
    bond_names = [b["name"] for b in topo.get("bonds", [])]
    available_ifaces = list(dict.fromkeys(br_names + bond_names + phys_names)) or ["eth0"]

    primary_iface = summary.get("primary_interface") or available_ifaces[0]
    unraid_cfg = unraid_file._parse_unraid_network_cfg()
    # what the host has: a value saved by an older version but never applied is not shown (SET-16)
    if "USE_DHCP[0]" in unraid_cfg:
        mode = "dhcp" if unraid_cfg["USE_DHCP[0]"].lower() == "yes" else "static"
    else:
        mode = "static" if summary.get("primary_ip") and summary["primary_ip"] != "?" else "dhcp"

    # Current IP
    current_ip = unraid_cfg.get("IPADDR[0]") or summary.get("primary_ip") or topology.read_ip()
    if current_ip == "?":
        current_ip = ""

    # Netmask & CIDR
    netmask = unraid_cfg.get("NETMASK[0]")
    if not netmask:
        for r in routes:
            if r.get("iface") == primary_iface and r.get("mask") and r["mask"] != "0.0.0.0":
                netmask = r["mask"]
                break
    if not netmask:
        netmask = "255.255.255.0"
    cidr = common._mask_to_cidr(netmask)

    # Gateway
    gateway = unraid_cfg.get("GATEWAY[0]") or summary.get("default_gateway") or ""

    # DNS
    dns_servers = list(summary.get("dns_servers") or [])
    if unraid_cfg.get("DNS_SERVER1") and unraid_cfg["DNS_SERVER1"] not in dns_servers:
        dns_servers.insert(0, unraid_cfg["DNS_SERVER1"])
    if unraid_cfg.get("DNS_SERVER2") and unraid_cfg["DNS_SERVER2"] not in dns_servers:
        dns_servers.append(unraid_cfg["DNS_SERVER2"])

    trial = None
    from backend import runtime

    if runtime.managed_host():  # the machine's own network service says, not a guess from the address
        from backend.hardware.net import managed

        mode = managed.mode_of(primary_iface)
        dns_servers = managed.dns_servers() or dns_servers
        trial = managed.trial_status()

    dns1 = dns_servers[0] if len(dns_servers) > 0 else ""
    dns2 = dns_servers[1] if len(dns_servers) > 1 else ""

    return {
        "status": "ok",
        "trial": trial,  # a change being tried: {interface, seconds_left, url}
        "mode": mode,
        "interface": primary_iface,
        "available_interfaces": available_ifaces,
        "ip_address": current_ip,
        "netmask": netmask,
        "cidr": cidr,
        "gateway": gateway,
        "dns1": dns1,
        "dns2": dns2,
        "dns_servers": dns_servers,
    }
