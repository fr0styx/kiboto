"""The address of a machine set up for Kiboto, with a way back.

Kiboto drives systemd-networkd: one file per interface in /etc/systemd/network, read before
Debian's or netplan's own, so the machine keeps the settings across restarts. A machine whose
network something else runs (ifupdown, NetworkManager) is shown and left alone.

A change is a trial. The old file is kept, and a timer of the machine itself, not of Kiboto,
which may be unreachable at the new address, puts it back after a while. Only a "keep" stops the
timer: from the page that made the change, or from a browser that opened the machine at its new
address with the trial's key in the link."""

import ipaddress
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, atomic_write_text, read_json
from backend.hardware.net import ipv4

DIR = "/etc/systemd/network"
PREFIX = "05-kiboto-"  # networkd takes the first file that matches: before netplan's and Debian's
LINK_PREFIX = "10-kiboto-"  # udev takes the first .link that matches: before the default naming (99-default.link)
STATE = os.path.join(DATA_DIR, "network_trial.json")
# On a machine Kiboto runs, the root service keeps the record here instead: the web process owns the
# data folder, and what the record names is written as root when a trial is put back (ADR 0006).
ROOT_STATE = "/var/lib/kiboto-door/network_trial.json"
_IFACE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,14}")
REVERT_UNIT = "kiboto-net-revert"
UPSTREAM_DNS = "/run/systemd/resolve/resolv.conf"  # the servers resolved asks, not its own 127.0.0.53
LEASES = "/run/systemd/netif/leases"
SYS_NET = "/sys/class/net"
APPLY_DELAY = 2.0  # the answer leaves before the address changes
DEFAULT_TRIAL, SHORTEST, LONGEST = 60, 10, 300
GRACE = 20  # the timer may run a little late
_IFACE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,14}$")
_NOT_A_PORT = ("lo", "docker", "veth", "br-", "virbr", "tailscale", "wg")
Run = Callable[..., tuple[int, str]]
BUSY = "A change to the network is still being tried. Keep it or go back first."
NOT_THIS = "That is not the change being tried."
_lock = threading.Lock()


def run(cmd: list[str], timeout: float = 20) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
        return done.returncode, (done.stdout or "").strip() or (done.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def after(seconds: float, what: Callable[[], None]) -> None:
    timer = threading.Timer(seconds, what)
    timer.daemon = True
    timer.start()


def networkd_runs(do: Run | None = None) -> bool:
    """Kiboto changes the address only where networkd and resolved run the machine's network."""
    do = do or run
    _, said = do(["systemctl", "is-active", "systemd-networkd", "systemd-resolved"])
    return said.split() == ["active", "active"]


FALLBACK = os.path.join(DIR, "99-kiboto-any-wired.network")
FALLBACK_TEXT = """# Written by Kiboto: a wired port that no other file names gets an address by DHCP, so the machine
# can still be reached after its network card moved to another slot or was replaced (the port then
# has a new name, and the file with its settings no longer matches it).
[Match]
Type=ether
Kind=!*

[Link]
RequiredForOnline=no

[Network]
DHCP=yes

[DHCPv4]
RouteMetric=2048
"""


def _own_file(prefix: str, name: str, suffix: str) -> str:
    """The path of one of Kiboto's own networkd files: only for a port name (letters, digits, _ . -,
    no slash), and always inside DIR. Names reach here from requests (VLANs, bonds, ports)."""
    if not _IFACE.match(name or ""):
        raise ValueError(f"{name or 'That'} is not a network port name.")
    base = os.path.normpath(DIR)
    path = os.path.normpath(os.path.join(base, f"{prefix}{name}{suffix}"))
    if not path.startswith(base + os.sep):
        raise ValueError(f"{name} is not a network port name.")
    return path


def link_for(iface: str) -> str:
    return _own_file(LINK_PREFIX, iface, ".link")


def pin_text(iface: str, mac: str) -> str:
    """The .link file that gives a network card the same port name in any slot."""
    return (
        f"# Written by Kiboto: the network card {mac} keeps the name {iface} in any slot, so the\n"
        "# settings Kiboto keeps for that port still find it after the card moved.\n"
        "[Match]\n"
        f"PermanentMACAddress={mac}\n"
        "\n"
        "[Link]\n"
        f"Name={iface}\n"
    )


def _write_pin(iface: str) -> bool:
    """A port of a network card keeps its name (a bridge or other port without a card has no
    device and no permanent address: never pinned). True when the file was written or changed."""
    if not _IFACE.match(iface or "") or not os.path.exists(os.path.join(SYS_NET, iface, "device")):
        return False
    mac = _mac(iface)
    if not mac or _text(link_for(iface)) == pin_text(iface, mac):
        return False
    os.makedirs(DIR, exist_ok=True)
    atomic_write_text(link_for(iface), pin_text(iface, mac))
    logger.info("[Network] %s keeps its name in any slot (%s)", iface, link_for(iface))
    return True


def _startup_image(do: Run) -> None:
    """Debian's start-up image names the ports before the system does, from its own copy of the
    .link files: it is made again after one changed."""
    code, said = do(["update-initramfs", "-u"], timeout=300)
    if code != 0:
        logger.warning("[Network] The start-up image was not made again: %s", said.strip()[-200:])


def pin(ifaces: list[str], do: Run | None = None) -> list[str]:
    """Pins the name of each port a card has, so a fixed address stays on the right port after the
    card moved to another slot (its new name no longer matched the settings). Returns those pinned."""
    do = do or run
    pinned = [iface for iface in ifaces if _write_pin(iface)]
    if pinned:
        _startup_image(do)
    return pinned


def ensure_pins(do: Run | None = None) -> list[str]:
    """Pins every port Kiboto keeps settings for, also on a machine set up before pins existed."""
    names = sorted(os.listdir(DIR)) if os.path.isdir(DIR) else []
    return pin(
        [n[len(PREFIX) : -len(".network")] for n in names if n.startswith(PREFIX) and n.endswith(".network")], do
    )


def ensure_fallback(do: Run | None = None) -> bool:
    """Writes the fallback for wired ports (FALLBACK) where networkd runs the network, and pins the
    names of the ports Kiboto keeps settings for (ensure_pins). True when the fallback was written."""
    do = do or run
    if not networkd_runs(do):
        return False
    ensure_pins(do)
    try:
        with open(FALLBACK, encoding="utf-8") as f:
            if f.read() == FALLBACK_TEXT:
                return False
    except OSError:  # not there yet
        logger.debug("[Network] %s is missing; writing it", FALLBACK)
    os.makedirs(DIR, exist_ok=True)
    atomic_write_text(FALLBACK, FALLBACK_TEXT)
    do(["networkctl", "reload"])
    logger.info("[Network] Wired ports without settings get an address by DHCP (%s)", FALLBACK)
    return True


def file_for(iface: str) -> str:
    return _own_file(PREFIX, iface, ".network")


def network_file(want: dict[str, Any]) -> str:
    """The networkd file for one interface."""
    out = [
        "# Written by Kiboto (Network, the address of this machine). A change made here is",
        "# overwritten by the next change in Kiboto; delete the file to hand the interface back.",
        "[Match]",
        f"Name={want['iface']}",
        "",
        "[Network]",
    ]
    if want["mode"] == "dhcp":
        out.append("DHCP=yes")
    else:
        out.append(f"Address={want['address']}/{want['prefix']}")
        if want["gateway"]:
            out.append(f"Gateway={want['gateway']}")
    out += [f"DNS={server}" for server in want["dns"]]
    if want["mode"] == "dhcp" and want["dns"]:
        out += ["", "[DHCPv4]", "UseDNS=no"]  # the servers chosen here, not the router's
    return "\n".join(out) + "\n"


def is_a_port(iface: str) -> bool:
    return (
        bool(_IFACE.match(iface or ""))
        and not iface.startswith(_NOT_A_PORT)
        and os.path.isdir(os.path.join(SYS_NET, iface))
    )


def checked(changes: dict[str, Any]) -> dict[str, Any]:
    """What was asked, checked and in one form. Raises ValueError with a sentence for the person."""
    iface = str(changes.get("interface") or "").strip()
    if not is_a_port(iface):
        raise ValueError(f"{iface or 'That'} is not a network port of this machine.")
    mode = str(changes.get("mode") or "static").strip().lower()
    if mode not in ("dhcp", "static"):
        raise ValueError("Choose a fixed address or an address from the router.")
    dns = []
    for name, label in (("dns1", "The first DNS server"), ("dns2", "The second DNS server")):
        if str(changes.get(name) or "").strip():
            server = ipv4.validate_ipv4(changes[name], label)
            if server not in dns:
                dns.append(server)
    want: dict[str, Any] = {"iface": iface, "mode": mode, "address": "", "prefix": 0, "gateway": "", "dns": dns}
    if mode == "static":
        address = ipv4.validate_ipv4(changes.get("ip_address") or "", "The address")
        mask = ipv4.validate_netmask(changes.get("netmask") or "")
        net = ipaddress.IPv4Network(f"{address}/{mask}", strict=False)
        if net.prefixlen < 8:
            raise ValueError("That subnet mask is too wide for a home or office network.")
        if net.prefixlen < 31 and ipaddress.IPv4Address(address) in (net.network_address, net.broadcast_address):
            raise ValueError(f"{address} is the network's own address or its broadcast address; choose one between.")
        gateway = ""
        if str(changes.get("gateway") or "").strip():
            gateway = ipv4.validate_ipv4(changes["gateway"], "The router's address")
            if gateway == address:
                raise ValueError("The router's address is the same as this machine's.")
            if ipaddress.IPv4Address(gateway) not in net:
                raise ValueError(f"The router {gateway} is not in the same network as {address}/{net.prefixlen}.")
        want.update(address=address, prefix=net.prefixlen, gateway=gateway)
    seconds = changes.get("timeout_sec")
    want["timeout"] = min(LONGEST, max(SHORTEST, int(seconds))) if seconds else DEFAULT_TRIAL
    return want


def _text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


# --- what the machine has now --------------------------------------------------------------------
def mode_of(iface: str) -> str:
    """'dhcp' or 'static': what Kiboto's own file says, else whether networkd holds a lease."""
    own = _text(file_for(iface))
    if own is not None:
        return "dhcp" if "DHCP=yes" in own else "static"
    index = _text(os.path.join(SYS_NET, iface, "ifindex"))  # not set in Kiboto yet: the machine itself says
    if index is None:
        return "dhcp"
    return "dhcp" if os.path.exists(os.path.join(LEASES, index.strip())) else "static"


def dns_servers() -> list[str]:
    out: list[str] = []
    try:
        with open(UPSTREAM_DNS, encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver" and ":" not in parts[1] and parts[1] not in out:
                    out.append(parts[1])
    except OSError:
        return []
    return out


# --- a trial ---------------------------------------------------------------------------------------
def _record() -> str:
    """Where the trial's record is kept: root's own folder when this is root on a machine Kiboto runs."""
    from backend import runtime

    return ROOT_STATE if os.geteuid() == 0 and runtime.managed_host() else STATE


def _ours(path: str) -> bool:
    """A file Kiboto itself writes for networkd or udev: nothing else is put back by a trial."""
    folder, name = os.path.split(str(path))
    return (
        os.path.normpath(str(path)) == path
        and folder == DIR
        and (
            (name.startswith(PREFIX) and name.endswith((".network", ".netdev")))
            or (name.startswith(LINK_PREFIX) and name.endswith(".link"))
        )
    )


def unsafe(trial: dict[str, Any]) -> str:
    """Why this record must not be acted on ("" when it may): it is put back as root, so every path
    is one of Kiboto's own network files, every text is text, and every interface is a name."""
    files = trial.get("files")
    if files is None:
        files = {trial.get("path"): trial.get("before")}  # a trial from before several files
    if not isinstance(files, dict) or not files:
        return "it names no files"
    for path, text in files.items():
        if not isinstance(path, str) or not _ours(path):
            return f"{path!r} is not one of Kiboto's network files"
        if text is not None and (not isinstance(text, str) or len(text) > 65536 or "\0" in text):
            return f"what was in {os.path.basename(path)} is not a network file's text"
    ifaces = trial.get("ifaces") or [trial.get("iface")]
    if not isinstance(ifaces, list) or not all(isinstance(i, str) and _IFACE.fullmatch(i) for i in ifaces):
        return "it names something that is not a network interface"
    for key in ("started", "timeout"):
        if not isinstance(trial.get(key), (int, float)) or isinstance(trial.get(key), bool):
            return f"its {key} is not a number"
    return ""


def _read(path: str) -> dict[str, Any] | None:
    data = read_json(path, None) if os.path.exists(path) else None
    return data if isinstance(data, dict) and data.get("id") else None


def _trial() -> dict[str, Any] | None:
    here = _record()
    data = _read(here)
    if data is None and here != STATE:
        # a trial begun by a version that kept the record in the data folder: taken only when root
        # wrote that file (the web process cannot make a file root's)
        try:
            if os.lstat(STATE).st_uid == 0 and not os.path.islink(STATE):
                data = _read(STATE)
        except OSError:
            data = None
    if data is None:
        return None
    why = unsafe(data)
    if why:
        logger.error("[Network] The record of the settings on trial is not used: %s", why)
        return None
    return data


def trial_status() -> dict[str, Any] | None:
    """For the page: which interface is on trial and how long is left. Never the trial's key."""
    trial = _trial()
    if not trial:
        return None
    left = int(trial["started"] + trial["timeout"] + APPLY_DELAY - time.time())
    return {"interface": trial["iface"], "seconds_left": max(0, left), "url": trial.get("plain_url", "")}


def _forget() -> None:
    for path in {_record(), STATE}:
        try:
            if os.path.lexists(path):
                os.remove(path)
        except OSError as e:
            logger.warning("[Network] %s could not be removed: %s", path, e)


def _reload(ifaces: list[str], do: Run) -> None:
    do(["networkctl", "reload"])
    for iface in ifaces:
        if os.path.isdir(os.path.join(SYS_NET, iface)):
            do(["networkctl", "reconfigure", iface])


def _link_of(netdev_text: str | None) -> str:
    found = re.search(r"^Name=(\S+)", netdev_text or "", re.M)
    return found.group(1) if found and _IFACE.match(found.group(1)) else ""


def _write_files(files: dict[str, str | None], ifaces: list[str], do: Run) -> None:
    """Writes each file (None removes it), lets networkd read them, and removes a bridge whose
    file went: networkd makes a bridge from its file but never takes one away."""
    gone_links = []
    for path, text in files.items():
        if text is None:
            if path.endswith(".netdev"):
                gone_links.append(_link_of(_text(path)))
            if os.path.exists(path):
                os.remove(path)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            atomic_write_text(path, text)
    for link in filter(None, gone_links):
        do(["ip", "link", "delete", link])
    _reload(ifaces, do)
    pin([iface for iface in ifaces if files.get(file_for(iface))], do)  # a port Kiboto gave settings to


def _put_back(trial: dict[str, Any], do: Run) -> None:
    before = trial.get("files") or {trial["path"]: trial.get("before")}  # a trial from before several files
    _write_files(before, trial.get("ifaces") or [trial["iface"]], do)


def settle(do: Run | None = None) -> bool:
    """A trial nobody kept in its time is put back. The machine's timer does that; after a restart
    in the middle of a trial the timer is gone, so Kiboto does it when it starts and before the
    next change."""
    do = do or run
    trial = _trial()
    if not trial:
        return False
    overdue = time.time() > trial["started"] + trial["timeout"] + APPLY_DELAY + GRACE
    if not overdue and do(["systemctl", "is-active", f"{REVERT_UNIT}.timer"])[1] == "active":
        return False
    go_back(None, do)
    return True


def start_trial(
    changes: dict[str, Any], do: Run | None = None, later: Callable[[float, Callable[[], None]], None] | None = None
) -> dict[str, Any]:
    """Arms the way back, then makes the change a moment later. Says how to keep it."""
    want = checked(changes)
    from backend import settings

    port = int(settings.current("port") or 8082)
    plain = f"http://{want['address']}:{port}" if want["mode"] == "static" else ""
    return _begin({file_for(want["iface"]): network_file(want)}, [want["iface"]], want["timeout"], plain, do, later)


def _begin(
    files: dict[str, str | None],
    ifaces: list[str],
    timeout: int,
    plain: str,
    do: Run | None = None,
    later: Callable[[float, Callable[[], None]], None] | None = None,
) -> dict[str, Any]:
    """A trial of new files: arms the machine's own way back, then writes them a moment later."""
    do, later = do or run, later or after
    settle(do)
    with _lock:
        if _trial():
            raise ValueError(BUSY)
        key = secrets.token_urlsafe(24)
        trial = {
            "id": key,
            "iface": ifaces[0],
            "ifaces": ifaces,
            "files": {path: _text(path) for path in files},
            "started": time.time(),
            "timeout": timeout,
            "plain_url": plain,
        }
        record = _record()
        os.makedirs(os.path.dirname(record), mode=0o700, exist_ok=True)
        atomic_write_json(record, trial)
        os.chmod(record, 0o600)
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
        code, said = do(
            [
                "systemd-run",
                "--quiet",
                "--collect",
                "--unit",
                REVERT_UNIT,
                f"--on-active={int(timeout + APPLY_DELAY)}",
                "--description",
                "Kiboto: back to the network settings from before the trial",
                "-p",
                f"WorkingDirectory={root}",
                "--setenv",
                f"DATA_DIR={DATA_DIR}",
                sys.executable,
                "-m",
                "backend.hardware.net.managed",
                "revert",
            ]
        )
        if code != 0:
            _forget()
            logger.warning("[Network] The way back could not be set up: %s", said)
            raise RuntimeError("The way back could not be set up, so nothing was changed.")

    def change() -> None:
        with _lock:
            if (_trial() or {}).get("id") != key:
                return  # taken back in the meantime
            _write_files(files, ifaces, do)
            logger.info("[Network] %s is on trial with new settings for %s s", ", ".join(ifaces), timeout)

    later(APPLY_DELAY, change)
    return {
        "status": "trial",
        "canary_id": key,
        "interface": ifaces[0],
        "timeout_sec": timeout,
        "url": f"{plain}/?keep-network={key}" if plain else "",
        "message": "The new settings are being tried.",
    }


# --- a bridge for virtual machines -----------------------------------------------------------------
BRIDGE = "br0"
QEMU_BRIDGES = "/etc/qemu/bridge.conf"


def netdev_for(link: str) -> str:
    return _own_file(PREFIX, link, ".netdev")


def bridge_status() -> dict[str, Any]:
    """Whether the bridge virtual machines join is there, and which port it holds."""
    port = re.search(r"^Name=(\S+)", "", re.M)
    on = os.path.exists(netdev_for(BRIDGE))
    for name in sorted(os.listdir(DIR)) if os.path.isdir(DIR) else []:
        text = _text(os.path.join(DIR, name)) or ""
        if name.startswith(PREFIX) and name.endswith(".network") and f"Bridge={BRIDGE}" in text:
            port = re.search(r"^Name=(\S+)", text, re.M)
    return {"on": on, "port": port.group(1) if (on and port) else "", "name": BRIDGE}


def _mac(iface: str) -> str:
    mac = (_text(os.path.join(SYS_NET, iface, "address")) or "").strip()
    return mac if re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", mac) else ""


def _address_settings_of(port: str, now: dict[str, Any], to: str = BRIDGE) -> str:
    """The [Network] settings the port has now, as a file for the bridge (or bond `to`): Kiboto's own
    file if there is one, else what the machine shows (`now`: an address from the router, or the fixed
    one it has)."""
    own = _text(file_for(port))
    if own and "Bridge=" not in own and "Bond=" not in own:
        return re.sub(r"^Name=\S+$", f"Name={to}", own, count=1, flags=re.M)
    want = {"iface": to, "mode": mode_of(port), "address": "", "prefix": 0, "gateway": "", "dns": []}
    if want["mode"] == "static":
        if not now.get("ip_address"):
            raise ValueError("The address of this machine could not be read, so it cannot be moved to a bridge.")
        want.update(address=now["ip_address"], prefix=int(now.get("cidr") or 24), gateway=now.get("gateway") or "")
        want["dns"] = [d for d in (now.get("dns1"), now.get("dns2")) if d]
    return network_file(want)


def _let_qemu_use(bridge: str) -> None:
    """QEMU's bridge helper only joins bridges listed in its settings."""
    text = _text(QEMU_BRIDGES) or ""
    if f"allow {bridge}" in text.split("\n"):
        return
    os.makedirs(os.path.dirname(QEMU_BRIDGES), exist_ok=True)
    atomic_write_text(QEMU_BRIDGES, text + ("" if not text or text.endswith("\n") else "\n") + f"allow {bridge}\n")


def start_bridge_trial(
    on: bool,
    port: str = "",
    now: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TRIAL,
    do: Run | None = None,
    later: Callable[[float, Callable[[], None]], None] | None = None,
) -> dict[str, Any]:
    """Puts the main port into a bridge that virtual machines join, the address moving to the
    bridge (with the port's own hardware address, so the router hands out the same one), or takes
    the bridge away again. A trial like any address change. `now` is the address the machine shows
    (host_ip.get_host_ip_config), for a port whose settings are not in Kiboto's own file."""
    if not networkd_runs(do):
        raise RuntimeError("This machine's network is not run by systemd-networkd.")
    there = bridge_status()
    if on == there["on"]:
        raise ValueError("The bridge is already there." if on else "There is no bridge to take away.")
    if on:
        if not is_a_port(port):
            raise ValueError(f"{port or 'That'} is not a network port of this machine.")
        _let_qemu_use(BRIDGE)
        mac = _mac(port)
        netdev = "\n".join(
            [
                "# Written by Kiboto: the bridge virtual machines join (Network, This machine).",
                "[NetDev]",
                f"Name={BRIDGE}",
                "Kind=bridge",
                *([f"MACAddress={mac}"] if mac else []),
                "",
                "[Bridge]",
                "STP=no",
                "",
            ]
        )
        files: dict[str, str | None] = {
            netdev_for(BRIDGE): netdev,
            file_for(BRIDGE): _address_settings_of(port, now or {}),
            file_for(
                port
            ): f"# Written by Kiboto: this port belongs to the bridge {BRIDGE}.\n[Match]\nName={port}\n\n[Network]\nBridge={BRIDGE}\n",
        }
        return _begin(files, [port, BRIDGE], timeout, "", do, later)
    port = there["port"]
    settings_now = _text(file_for(BRIDGE)) or network_file(
        {"iface": port, "mode": "dhcp", "address": "", "prefix": 0, "gateway": "", "dns": []}
    )
    files: dict[str, str | None] = {
        file_for(port): re.sub(rf"^Name={BRIDGE}$", f"Name={port}", settings_now, count=1, flags=re.M),
        file_for(BRIDGE): None,
        netdev_for(BRIDGE): None,
    }
    return _begin(files, [port], timeout, "", do, later)


# --- VLANs and packet size: a port's other settings ----------------------------------------------
MTU_RANGE = (576, 9216)  # IPv4's smallest a router must take, to jumbo frames


def _port_settings(port: str, now: dict[str, Any] | None = None) -> str:
    """The port's settings as a file of Kiboto's own: its file if Kiboto wrote one, else what the port
    has now (an address from the router, or the fixed one the machine shows in `now`)."""
    own = _text(file_for(port))
    if own is not None:
        return own
    want = {"iface": port, "mode": mode_of(port), "address": "", "prefix": 0, "gateway": "", "dns": []}
    if want["mode"] == "static":
        now = now or {}
        if not now.get("ip_address"):
            raise ValueError(f"The address of {port} could not be read; set it on this page first.")
        want.update(address=now["ip_address"], prefix=int(now.get("cidr") or 24), gateway=now.get("gateway") or "")
        want["dns"] = [d for d in (now.get("dns1"), now.get("dns2")) if d]
    return network_file(want)


def _section_lines(text: str, section: str, key: str, values: list[str]) -> str:
    """The file with every `key=` line of `section` replaced by one line per value (none: removed)."""
    lines = text.rstrip("\n").split("\n")
    out: list[str] = []
    current, placed = "", False
    for line in lines:
        head = re.fullmatch(r"\[(\w+)\]", line.strip())
        if head:
            if current == section and not placed:
                while out and not out[-1]:
                    out.pop()
                out += [f"{key}={v}" for v in values] + [""]
                placed = True
            current = head.group(1)
            out.append(line)
            continue
        if current == section and line.startswith(f"{key}="):
            continue
        out.append(line)
    if current == section and not placed:
        out += [f"{key}={v}" for v in values]
        placed = True
    if not placed and values:
        out += ["", f"[{section}]", *[f"{key}={v}" for v in values]]
    return "\n".join(out).rstrip("\n") + "\n"


def _vlans_of(text: str) -> list[str]:
    return re.findall(r"^VLAN=(\S+)$", text or "", re.M)


def vlan_link(parent: str, vlan_id: int) -> str:
    name = f"{parent}.{vlan_id}"
    if len(name) > 15:
        raise ValueError(f"The name {name} is longer than Linux allows (15 characters).")
    return name


def start_vlan_trial(
    parent: str,
    vlan_id: int,
    now: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TRIAL,
    do: Run | None = None,
    later: Callable[[float, Callable[[], None]], None] | None = None,
) -> dict[str, Any]:
    """A tagged sub-port (802.1Q) on a port, as a trial: the port keeps its address and names the
    VLAN; the VLAN starts with no address (it is given one like any port, on this page)."""
    if not networkd_runs(do):
        raise RuntimeError("This machine's network is not run by systemd-networkd.")
    if not is_a_port(parent) or "." in parent:
        raise ValueError(f"{parent or 'That'} is not a network port a VLAN can be added to.")
    if not isinstance(vlan_id, int) or isinstance(vlan_id, bool) or not 1 <= vlan_id <= 4094:
        raise ValueError("A VLAN number is between 1 and 4094.")
    name = vlan_link(parent, vlan_id)
    if os.path.exists(os.path.join(SYS_NET, name)) or os.path.exists(netdev_for(name)):
        raise ValueError(f"The VLAN {name} is already there.")
    settings = _port_settings(parent, now)
    if "Bridge=" in settings or "Bond=" in settings:
        raise ValueError(f"{parent} belongs to a bridge or bond; add the VLAN to that instead.")
    netdev = "\n".join(
        [
            f"# Written by Kiboto: VLAN {vlan_id} on {parent} (Network, This machine).",
            "[NetDev]",
            f"Name={name}",
            "Kind=vlan",
            "",
            "[VLAN]",
            f"Id={vlan_id}",
            "",
        ]
    )
    files: dict[str, str | None] = {
        netdev_for(name): netdev,
        file_for(name): (
            f"# Written by Kiboto: VLAN {vlan_id} on {parent}, with no address of its own yet.\n"
            f"[Match]\nName={name}\n\n[Network]\nLinkLocalAddressing=no\nConfigureWithoutCarrier=yes\n"
        ),
        file_for(parent): _section_lines(settings, "Network", "VLAN", sorted({*_vlans_of(settings), name})),
    }
    return _begin(files, [parent, name], timeout, "", do, later)


def start_vlan_removal(
    name: str,
    timeout: int = DEFAULT_TRIAL,
    do: Run | None = None,
    later: Callable[[float, Callable[[], None]], None] | None = None,
) -> dict[str, Any]:
    """Takes away a VLAN Kiboto made, as a trial (the port it was on stays as it is)."""
    if not networkd_runs(do):
        raise RuntimeError("This machine's network is not run by systemd-networkd.")
    netdev = _text(netdev_for(name)) if _IFACE.match(name or "") else None
    if not netdev or "Kind=vlan" not in netdev:
        raise ValueError(f"{name or 'That'} is not a VLAN Kiboto made.")
    parent = name.rsplit(".", 1)[0]
    settings = _text(file_for(parent)) or ""
    files: dict[str, str | None] = {netdev_for(name): None, file_for(name): None}
    if settings:
        files[file_for(parent)] = _section_lines(
            settings, "Network", "VLAN", [v for v in _vlans_of(settings) if v != name]
        )
    return _begin(files, [parent], timeout, "", do, later)


def start_mtu_trial(
    port: str,
    mtu: int,
    now: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TRIAL,
    do: Run | None = None,
    later: Callable[[float, Callable[[], None]], None] | None = None,
) -> dict[str, Any]:
    """A port's packet size (MTU), as a trial. The size it has already: nothing to try."""
    if not networkd_runs(do):
        raise RuntimeError("This machine's network is not run by systemd-networkd.")
    if not is_a_port(port):
        raise ValueError(f"{port or 'That'} is not a network port of this machine.")
    if not isinstance(mtu, int) or isinstance(mtu, bool) or not MTU_RANGE[0] <= mtu <= MTU_RANGE[1]:
        raise ValueError(f"The packet size is between {MTU_RANGE[0]} and {MTU_RANGE[1]} bytes.")
    have = (_text(os.path.join(SYS_NET, port, "mtu")) or "").strip()
    if have == str(mtu):
        return {"status": "ok", "interface": port, "mtu": mtu, "changed": False}
    settings = _port_settings(port, now)
    files: dict[str, str | None] = {file_for(port): _section_lines(settings, "Link", "MTUBytes", [str(mtu)])}
    return _begin(files, [port], timeout, "", do, later)


# --- a bond: ports as one --------------------------------------------------------------------------
BOND = "bond0"
# the page's numbers (Linux's bonding modes) and networkd's names
BOND_MODES = {"0": "balance-rr", "1": "active-backup", "2": "balance-xor", "4": "802.3ad", "6": "balance-alb"}


def bond_status() -> dict[str, Any]:
    """Whether Kiboto's bond is there, and which ports it holds (the first carried the address)."""
    netdev = _text(netdev_for(BOND))
    members = []
    for name in sorted(os.listdir(DIR)) if os.path.isdir(DIR) else []:
        text = _text(os.path.join(DIR, name)) or ""
        if name.startswith(PREFIX) and name.endswith(".network") and f"Bond={BOND}" in text:
            found = re.search(r"^Name=(\S+)", text, re.M)
            if found:
                members.append(found.group(1))
    first = re.search(r"^# first: (\S+)$", netdev or "", re.M)
    return {"on": netdev is not None, "members": members, "first": first.group(1) if first else "", "name": BOND}


def start_bond_trial(
    members: list[str],
    mode: str = "1",
    miimon: int = 100,
    now: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TRIAL,
    do: Run | None = None,
    later: Callable[[float, Callable[[], None]], None] | None = None,
) -> dict[str, Any]:
    """Two or more ports as one (bond0), as a trial: the address of the port the machine is reached on
    (else the first listed) moves to the bond, with that port's hardware address, so the router hands
    out the same one. A bond that is there already gets the new ports and mode."""
    if not networkd_runs(do):
        raise RuntimeError("This machine's network is not run by systemd-networkd.")
    members = [str(m) for m in members] if isinstance(members, list) else []
    if len(members) < 2 or len(set(members)) != len(members):
        raise ValueError("A bond needs two or more different ports.")
    for port in members:
        if not is_a_port(port) or "." in port or port in (BOND, BRIDGE):
            raise ValueError(f"{port or 'That'} is not a network port that can join a bond.")
        settings = _text(file_for(port)) or ""
        if "Bridge=" in settings or "VLAN=" in settings:
            raise ValueError(f"{port} carries a bridge or VLANs; take those away first.")
    if str(mode) not in BOND_MODES:
        raise ValueError("Choose one of the bonding modes offered.")
    if not isinstance(miimon, int) or isinstance(miimon, bool) or not 10 <= miimon <= 1000:
        raise ValueError("The link check runs every 10 to 1000 milliseconds.")
    if bridge_status()["on"]:
        raise ValueError("Take the bridge for virtual machines away first; a bond and that bridge do not mix yet.")
    there = bond_status()
    # the port the machine is reached on carries on as the bond's first: its address and hardware address
    main = str((now or {}).get("interface") or "")
    first = there["first"] if there["on"] and there["first"] in members else (main if main in members else members[0])
    mac = _mac(first)
    netdev = "\n".join(
        [
            "# Written by Kiboto: ports as one (Network, This machine).",
            f"# first: {first}",
            "[NetDev]",
            f"Name={BOND}",
            "Kind=bond",
            *([f"MACAddress={mac}"] if mac else []),
            "",
            "[Bond]",
            f"Mode={BOND_MODES[str(mode)]}",
            f"MIIMonitorSec={miimon}ms",
            *(["LACPTransmitRate=fast"] if str(mode) == "4" else []),
            "",
        ]
    )
    files: dict[str, str | None] = {netdev_for(BOND): netdev}
    if not there["on"]:
        files[file_for(BOND)] = _address_settings_of(first, now or {}, to=BOND)
    for port in members:
        # the port that had the address is the one used while it has a link (active-backup)
        primary = "PrimarySlave=true\n" if port == first else ""
        files[file_for(port)] = (
            f"# Written by Kiboto: this port belongs to the bond {BOND}.\n[Match]\nName={port}\n\n[Network]\nBond={BOND}\n{primary}"
        )
    for port in there["members"]:
        if port not in members:  # left the bond: back on an address from the router
            files[file_for(port)] = None
    return _begin(files, [*members, BOND], timeout, "", do, later)


def start_bond_removal(
    timeout: int = DEFAULT_TRIAL,
    do: Run | None = None,
    later: Callable[[float, Callable[[], None]], None] | None = None,
) -> dict[str, Any]:
    """Takes Kiboto's bond apart, as a trial: its address goes back to the port that had it first,
    and the other ports get an address from the router again."""
    if not networkd_runs(do):
        raise RuntimeError("This machine's network is not run by systemd-networkd.")
    there = bond_status()
    if not there["on"]:
        raise ValueError("There is no bond of Kiboto's to take apart.")
    first = there["first"] or (there["members"][0] if there["members"] else "")
    if not first:
        raise ValueError("The bond's ports could not be found.")
    settings = _text(file_for(BOND)) or network_file(
        {"iface": first, "mode": "dhcp", "address": "", "prefix": 0, "gateway": "", "dns": []}
    )
    files: dict[str, str | None] = {
        file_for(first): re.sub(rf"^Name={BOND}$", f"Name={first}", settings, count=1, flags=re.M),
        file_for(BOND): None,
        netdev_for(BOND): None,
    }
    for port in there["members"]:
        if port != first:
            files[file_for(port)] = None
    return _begin(files, [first, *[p for p in there["members"] if p != first]], timeout, "", do, later)


def keep(key: str | None, do: Run | None = None) -> dict[str, Any]:
    """The trial's settings stay. `key` None is the administrator on the page that made the change."""
    do = do or run
    with _lock:
        trial = _trial()
        if not trial:
            return {"status": "ok", "kept": False}
        if key is not None and not secrets.compare_digest(str(key), str(trial["id"])):
            raise ValueError(NOT_THIS)
        do(["systemctl", "stop", f"{REVERT_UNIT}.timer"])
        _forget()
    logger.info("[Network] The new settings for %s are kept", trial["iface"])
    return {"status": "ok", "kept": True, "interface": trial["iface"]}


def go_back(key: str | None, do: Run | None = None, stop_timer: bool = True) -> dict[str, Any]:
    """The settings from before the trial, now."""
    do = do or run
    with _lock:
        trial = _trial()
        if not trial:
            return {"status": "ok", "reverted": False}
        if key is not None and not secrets.compare_digest(str(key), str(trial["id"])):
            raise ValueError(NOT_THIS)
        _put_back(trial, do)
        if stop_timer:
            do(["systemctl", "stop", f"{REVERT_UNIT}.timer"])
        _forget()
    logger.info("[Network] %s is back on the settings from before the trial", trial["iface"])
    return {"status": "ok", "reverted": True, "interface": trial["iface"]}


def main(argv: list[str]) -> int:
    """The machine's own timer: `revert` puts back what was there when nobody kept the trial."""
    if argv[1:2] != ["revert"]:
        return 2
    go_back(None, stop_timer=False)  # the timer is this very run
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
