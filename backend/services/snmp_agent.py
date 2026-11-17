"""SNMP v3 agent (owner, 10 Nov 2026 and decision of 16 Nov evening): monitoring tools such as
LibreNMS, Zabbix or PRTG read how the NAS is doing. Off by default; version 3 only, always with
authentication (SHA-256) and encryption (AES-128), so nothing answers without the user name and
both passwords; v1 and v2c requests get no answer. Read-only: nothing can be changed over SNMP.

What it answers: the system group (SNMPv2-MIB), uptime, memory, the storage pool and processor
load (HOST-RESOURCES-MIB), interfaces with 64-bit counters (IF-MIB) and the load average and
memory figures of UCD-SNMP-MIB that most tools graph. Figures are read from the host's /proc at
most every few seconds; the storage pool is read with statfs, which does not wake sleeping drives.
"""

from __future__ import annotations

import asyncio
import bisect
import logging
import os
import shutil
import socket
import threading
import time
from typing import Any

from backend.config import DATA_DIR, HOST_PROC, POOL_PATH
from backend.fsutil import atomic_write_json, read_json

logger = logging.getLogger(__name__)

STATE_FILE = os.path.join(DATA_DIR, "snmp.json")
DEFAULT_PORT = 161
MIN_PASSWORD = 8  # RFC 3414: shorter passwords are refused
FRESH_SECS = 5.0
OID = tuple[int, ...]

SYSTEM = (1, 3, 6, 1, 2, 1, 1)
IF_TABLE = (1, 3, 6, 1, 2, 1, 2, 2, 1)
IFX_TABLE = (1, 3, 6, 1, 2, 1, 31, 1, 1, 1)
HR = (1, 3, 6, 1, 2, 1, 25)
UCD = (1, 3, 6, 1, 4, 1, 2021)
NET_SNMP_LINUX = (1, 3, 6, 1, 4, 1, 8072, 3, 2, 10)  # what Linux agents say they are; tools know it
HR_STORAGE_RAM = HR + (2, 1, 2)
HR_STORAGE_FIXED = HR + (2, 1, 4)


def _defaults() -> dict[str, Any]:
    return {
        "enabled": False,
        "port": DEFAULT_PORT,
        "user": "",
        "auth": "",
        "priv": "",
        "contact": "",
        "location": "",
    }


def _raw() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    return {**_defaults(), **(data if isinstance(data, dict) else {})}


def public_state() -> dict[str, Any]:
    """What the page may see: never the passwords, only whether they are set; and whether the
    agent answers right now."""
    st = _raw()
    out = {k: v for k, v in st.items() if k not in ("auth", "priv")}
    out["passwords_set"] = bool(st.get("auth") and st.get("priv"))
    out.update(_agent.status())
    out["protocols"] = {"auth": "SHA-256", "priv": "AES-128"}
    return out


def save(
    enabled: bool,
    port: int,
    user: str,
    auth_password: str | None,
    priv_password: str | None,
    contact: str = "",
    location: str = "",
) -> dict[str, Any]:
    """Saves the settings and starts or stops the agent. A password of None keeps the stored one.
    Raises ValueError with a sentence for the page when the settings cannot work."""
    from backend.errors import SaidError
    from backend.secret_box import seal

    st = _raw()
    user = (user or "").strip()
    if not 1 <= int(port) <= 65535:
        raise SaidError("Choose a port between 1 and 65535 (SNMP uses 161).", "snmp_port")
    if user and (len(user) > 32 or not all(ch.isalnum() or ch in "-_." for ch in user)):
        raise SaidError("Use up to 32 letters, digits, dots, hyphens or underscores for the user name.", "snmp_user")
    for label, pw in (("authentication", auth_password), ("encryption", priv_password)):
        if pw is not None and len(pw) < MIN_PASSWORD:
            raise SaidError(
                f"The {label} password needs at least {MIN_PASSWORD} characters.", f"snmp_{label}_short", n=MIN_PASSWORD
            )
    if auth_password is not None:
        st["auth"] = seal(auth_password)
    if priv_password is not None:
        st["priv"] = seal(priv_password)
    if enabled and not (user and st.get("auth") and st.get("priv")):
        raise SaidError("Fill in the user name and both passwords before turning it on.", "snmp_fill_in")
    if enabled and auth_password is not None and auth_password == priv_password:
        raise SaidError("Use two different passwords for authentication and encryption.", "snmp_same_passwords")
    st.update(
        {
            "enabled": bool(enabled),
            "port": int(port),
            "user": user,
            "contact": (contact or "").strip()[:255],
            "location": (location or "").strip()[:255],
        }
    )
    atomic_write_json(STATE_FILE, st)
    apply()
    return public_state()


# ---- what the agent answers -------------------------------------------------------------------


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _meminfo(proc: str) -> dict[str, int]:
    out = {}
    for line in _read(os.path.join(proc, "meminfo")).splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            out[key.strip()] = int(parts[0])  # kB
    return out


def _interfaces(proc: str) -> list[dict[str, Any]]:
    """The host's interfaces (PID 1's network namespace), loopback and container veths left out."""
    text = _read(os.path.join(proc, "1", "net", "dev")) or _read(os.path.join(proc, "net", "dev"))
    out = []
    for line in text.splitlines()[2:]:
        name, _, rest = line.partition(":")
        name = name.strip()
        nums = rest.split()
        if not name or name == "lo" or name.startswith("veth") or len(nums) < 9:
            continue
        out.append({"name": name, "rx": int(nums[0]), "tx": int(nums[8])})
    return out


class _Cpu:
    """Processor load from the change in /proc/stat between two readings."""

    def __init__(self) -> None:
        self.last: dict[str, tuple[int, int]] = {}

    def loads(self, proc: str) -> list[int]:
        out = []
        for line in _read(os.path.join(proc, "stat")).splitlines():
            if not line.startswith("cpu") or line.startswith("cpu "):
                continue
            name, *vals = line.split()
            nums = [int(v) for v in vals[:8] if v.isdigit()]
            total, idle = sum(nums), (nums[3] + nums[4]) if len(nums) > 4 else 0
            prev = self.last.get(name)
            self.last[name] = (total, idle)
            if prev and total > prev[0]:
                out.append(round(100 * (1 - (idle - prev[1]) / (total - prev[0]))))
            else:
                out.append(0)
        return out


_cpu = _Cpu()


def mib(
    proc: str = HOST_PROC, pool: str = POOL_PATH, started: float | None = None, host_root: str = "/host"
) -> dict[OID, Any]:
    """Every OID the agent answers, with its value now."""
    from pysnmp.proto.api import v2c

    st = _raw()
    started = started if started is not None else _agent.started or time.time()
    host = (
        _read(os.path.join(host_root, "etc", "hostname")).strip() or os.environ.get("NAS_NAME") or os.uname().nodename
    )
    kernel = _read(os.path.join(proc, "sys", "kernel", "osrelease")).strip() or os.uname().release
    up = _read(os.path.join(proc, "uptime")).split()
    host_ticks = int(float(up[0]) * 100) if up else 0
    t: dict[OID, Any] = {
        SYSTEM + (1, 0): v2c.OctetString(f"Kiboto NAS, Linux {kernel}"),
        SYSTEM + (2, 0): v2c.ObjectIdentifier(NET_SNMP_LINUX),
        SYSTEM + (3, 0): v2c.TimeTicks(int((time.time() - started) * 100) % 2**32),
        SYSTEM + (4, 0): v2c.OctetString(st.get("contact") or ""),
        SYSTEM + (5, 0): v2c.OctetString(host),
        SYSTEM + (6, 0): v2c.OctetString(st.get("location") or ""),
        SYSTEM + (7, 0): v2c.Integer(72),
        HR + (1, 1, 0): v2c.TimeTicks(host_ticks % 2**32),
    }
    mem = _meminfo(proc)
    if mem:
        t[HR + (2, 2, 0)] = v2c.Integer(min(mem.get("MemTotal", 0), 2**31 - 1))  # hrMemorySize, kB
        t[UCD + (4, 5, 0)] = v2c.Integer(min(mem.get("MemTotal", 0), 2**31 - 1))
        t[UCD + (4, 6, 0)] = v2c.Integer(min(mem.get("MemAvailable", mem.get("MemFree", 0)), 2**31 - 1))
        t[UCD + (4, 3, 0)] = v2c.Integer(min(mem.get("SwapTotal", 0), 2**31 - 1))
        t[UCD + (4, 4, 0)] = v2c.Integer(min(mem.get("SwapFree", 0), 2**31 - 1))
    # hrStorageTable: 1 physical memory, 2 the storage pool
    rows: list[tuple[OID, str, int, int, int]] = []
    if mem:
        used = mem.get("MemTotal", 0) - mem.get("MemAvailable", mem.get("MemFree", 0))
        rows.append((HR_STORAGE_RAM, "Physical memory", 1024, mem.get("MemTotal", 0), used))
    try:
        du = shutil.disk_usage(pool)
        unit = 4096
        rows.append((HR_STORAGE_FIXED, pool, unit, du.total // unit, du.used // unit))
    except OSError:
        pass
    for i, (kind, descr, unit, size, used) in enumerate(rows, start=1):
        base = HR + (2, 3, 1)
        t[base + (1, i)] = v2c.Integer(i)
        t[base + (2, i)] = v2c.ObjectIdentifier(kind)
        t[base + (3, i)] = v2c.OctetString(descr)
        t[base + (4, i)] = v2c.Integer(unit)
        t[base + (5, i)] = v2c.Integer(min(size, 2**31 - 1))
        t[base + (6, i)] = v2c.Integer(min(used, 2**31 - 1))
    for i, load in enumerate(_cpu.loads(proc), start=1):
        t[HR + (3, 3, 1, 2, 196607 + i)] = v2c.Integer(load)  # hrProcessorLoad, indexed like net-snmp
    la = _read(os.path.join(proc, "loadavg")).split()
    for i, (minutes, value) in enumerate(zip((1, 5, 15), la[:3], strict=False), start=1):
        t[UCD + (10, 1, 1, i)] = v2c.Integer(i)
        t[UCD + (10, 1, 2, i)] = v2c.OctetString(f"Load-{minutes}")
        t[UCD + (10, 1, 3, i)] = v2c.OctetString(value)
    nics = _interfaces(proc)
    t[(1, 3, 6, 1, 2, 1, 2, 1, 0)] = v2c.Integer(len(nics))
    for i, nic in enumerate(nics, start=1):
        oper = _read(os.path.join(host_root, "sys", "class", "net", nic["name"], "operstate")).strip()
        t[IF_TABLE + (1, i)] = v2c.Integer(i)
        t[IF_TABLE + (2, i)] = v2c.OctetString(nic["name"])
        t[IF_TABLE + (3, i)] = v2c.Integer(6)  # ethernetCsmacd
        t[IF_TABLE + (8, i)] = v2c.Integer(2 if oper == "down" else 1)
        t[IF_TABLE + (10, i)] = v2c.Counter32(nic["rx"] % 2**32)
        t[IF_TABLE + (16, i)] = v2c.Counter32(nic["tx"] % 2**32)
        t[IFX_TABLE + (1, i)] = v2c.OctetString(nic["name"])
        t[IFX_TABLE + (6, i)] = v2c.Counter64(nic["rx"])
        t[IFX_TABLE + (10, i)] = v2c.Counter64(nic["tx"])
    return t


class _Tree:
    """The answers, read again at most every FRESH_SECS seconds."""

    def __init__(self, build=None) -> None:
        self.build = build or (lambda: mib())
        self.at = 0.0
        self.values: dict[OID, Any] = {}
        self.keys: list[OID] = []
        self.lock = threading.Lock()

    def now(self) -> tuple[dict[OID, Any], list[OID]]:
        with self.lock:
            if time.monotonic() - self.at > FRESH_SECS or not self.keys:
                self.values = self.build()
                self.keys = sorted(self.values)
                self.at = time.monotonic()
            return self.values, self.keys


def controller(tree: _Tree) -> Any:
    """A read-only MIB controller over the tree, for pysnmp's command responders."""
    from pysnmp.proto import rfc1905
    from pysnmp.proto.api import v2c
    from pysnmp.smi import instrum

    class Controller(instrum.AbstractMibInstrumController):
        def read_variables(self, *var_binds, **context):
            values, _ = tree.now()
            return [(oid, values.get(tuple(oid), rfc1905.noSuchObject)) for oid, _ in var_binds]

        def read_next_variables(self, *var_binds, **context):
            values, keys = tree.now()
            out = []
            for oid, _ in var_binds:
                i = bisect.bisect_right(keys, tuple(oid))
                if i < len(keys):
                    out.append((v2c.ObjectIdentifier(keys[i]), values[keys[i]]))
                else:
                    out.append((oid, rfc1905.endOfMibView))
            return out

        def write_variables(self, *var_binds, **context):
            return [(oid, rfc1905.noSuchObject) for oid, _ in var_binds]

    return Controller()


class _Agent:
    """The listening agent: its own thread and event loop, started and stopped with the settings."""

    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.engine: Any = None
        self.started = 0.0
        self.port = 0
        self.error = ""

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self.thread and self.thread.is_alive()),
            "listening_port": self.port,
            "error": self.error,
        }

    def start(self, port: int, user: str, auth: str, priv: str, host: str = "0.0.0.0") -> bool:  # noqa: S104
        from pysnmp.carrier.asyncio.dgram import udp
        from pysnmp.entity import config, engine
        from pysnmp.entity.rfc3413 import cmdrsp, context

        self.stop()
        self.error = ""
        ready = threading.Event()

        def run() -> None:
            from pysnmp.error import PySnmpError

            loop = asyncio.new_event_loop()
            self.loop = loop
            asyncio.set_event_loop(loop)
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    sock.bind((host, port))  # here, so a port in use is said now and not lost in the loop
                except OSError:
                    sock.close()
                    raise
                eng = engine.SnmpEngine()
                config.add_transport(eng, udp.DOMAIN_NAME, udp.UdpAsyncioTransport().open_server_mode(sock=sock))
                config.add_v3_user(eng, user, config.USM_AUTH_HMAC192_SHA256, auth, config.USM_PRIV_CFB128_AES, priv)
                config.add_vacm_user(eng, 3, user, "authPriv", (1, 3, 6, 1), ())
                ctx = context.SnmpContext(eng)
                ctx.unregister_context_name(b"")
                ctx.register_context_name(b"", controller(_Tree()))
                for responder in (cmdrsp.GetCommandResponder, cmdrsp.NextCommandResponder, cmdrsp.BulkCommandResponder):
                    responder(eng, ctx)
            except (OSError, RuntimeError, ValueError, PySnmpError) as e:
                self.error = f"UDP {port} could not be opened: {e}"
                logger.warning("SNMP agent not started: %s", self.error)
                loop.close()
                ready.set()
                return
            self.engine = eng
            self.port, self.error, self.started = port, "", time.time()
            ready.set()
            loop.run_forever()
            eng.close_dispatcher()
            loop.close()

        self.thread = threading.Thread(target=run, daemon=True, name="snmp-agent")
        self.thread.start()
        ready.wait(5)
        if self.error:
            self.thread.join(1)
            self.thread = None
            return False
        logger.info("SNMP v3 agent answers on UDP %s", port)
        return True

    def stop(self) -> None:
        if self.loop and self.thread and self.thread.is_alive():
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(5)
        self.thread = None
        self.loop = None
        self.engine = None
        self.port = 0


_agent = _Agent()


def apply() -> dict[str, Any]:
    """Starts the agent when it is on and stops it when it is off (at startup and after a save)."""
    from backend.secret_box import unseal

    st = _raw()
    if not st.get("enabled"):
        _agent.stop()
        _agent.error = ""
        return _agent.status()
    port = int(st.get("port") or DEFAULT_PORT)
    _agent.start(port, st["user"], unseal(st.get("auth") or ""), unseal(st.get("priv") or ""))
    return _agent.status()


def stop() -> None:
    """Closes the agent's port (at shutdown)."""
    _agent.stop()
