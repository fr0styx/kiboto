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
STATE = os.path.join(DATA_DIR, "network_trial.json")
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


def file_for(iface: str) -> str:
    return os.path.join(DIR, f"{PREFIX}{iface}.network")


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
def _trial() -> dict[str, Any] | None:
    data = read_json(STATE, None) if os.path.exists(STATE) else None
    return data if isinstance(data, dict) and data.get("id") else None


def trial_status() -> dict[str, Any] | None:
    """For the page: which interface is on trial and how long is left. Never the trial's key."""
    trial = _trial()
    if not trial:
        return None
    left = int(trial["started"] + trial["timeout"] + APPLY_DELAY - time.time())
    return {"interface": trial["iface"], "seconds_left": max(0, left), "url": trial.get("plain_url", "")}


def _forget() -> None:
    if os.path.exists(STATE):
        os.remove(STATE)


def _reload(iface: str, do: Run) -> None:
    do(["networkctl", "reload"])
    do(["networkctl", "reconfigure", iface])


def _put_back(trial: dict[str, Any], do: Run) -> None:
    path = trial["path"]
    if trial.get("before") is None:
        if os.path.exists(path):
            os.remove(path)
    else:
        atomic_write_text(path, trial["before"])
    _reload(trial["iface"], do)


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
    do, later = do or run, later or after
    want = checked(changes)
    settle(do)
    with _lock:
        if _trial():
            raise ValueError(BUSY)
        path = file_for(want["iface"])
        before = _text(path)
        from backend import settings

        port = int(settings.current("port") or 8082)
        key = secrets.token_urlsafe(24)
        plain = f"http://{want['address']}:{port}" if want["mode"] == "static" else ""
        trial = {
            "id": key,
            "iface": want["iface"],
            "path": path,
            "before": before,
            "started": time.time(),
            "timeout": want["timeout"],
            "plain_url": plain,
        }
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        atomic_write_json(STATE, trial)
        os.chmod(STATE, 0o600)
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
        code, said = do(
            [
                "systemd-run",
                "--quiet",
                "--collect",
                "--unit",
                REVERT_UNIT,
                f"--on-active={int(want['timeout'] + APPLY_DELAY)}",
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
    text = network_file(want)

    def change() -> None:
        with _lock:
            if (_trial() or {}).get("id") != key:
                return  # taken back in the meantime
            os.makedirs(DIR, exist_ok=True)
            atomic_write_text(path, text)
            _reload(want["iface"], do)
            logger.info("[Network] %s is on trial with new settings for %s s", want["iface"], want["timeout"])

    later(APPLY_DELAY, change)
    return {
        "status": "trial",
        "canary_id": key,
        "interface": want["iface"],
        "timeout_sec": want["timeout"],
        "url": f"{plain}/?keep-network={key}" if plain else "",
        "message": "The new settings are being tried.",
    }


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
