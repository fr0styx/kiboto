"""IPv4 addresses and subnet masks as a person types them, checked and in one form."""

import ipaddress


def validate_ipv4(val: str, field_name: str) -> str:
    val = (val or "").strip()
    if not val:
        raise ValueError(f"{field_name} is required")
    try:
        ip = ipaddress.IPv4Address(val)
    except ValueError:
        raise ValueError(f"Invalid IPv4 address for {field_name}: {val}") from None
    if ip.is_loopback:
        raise ValueError(f"{field_name} cannot be a loopback address (127.0.0.0/8)")
    if ip.is_multicast:
        raise ValueError(f"{field_name} cannot be a multicast address")
    if ip.is_unspecified:
        raise ValueError(f"{field_name} cannot be 0.0.0.0")
    if str(ip) == "255.255.255.255":
        raise ValueError(f"{field_name} cannot be broadcast address")
    return str(ip)


def validate_netmask(val: str) -> str:
    val = (val or "").strip()
    if not val:
        return "255.255.255.0"
    if val.startswith("/"):
        val = val[1:]
    if val.isdigit():
        prefix = int(val)
        if 1 <= prefix <= 32:
            return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)
        raise ValueError(f"Invalid CIDR prefix: /{prefix}")
    try:
        net = ipaddress.IPv4Network(f"0.0.0.0/{val}")
        return str(net.netmask)
    except ValueError:
        raise ValueError(f"Invalid netmask: {val}") from None
