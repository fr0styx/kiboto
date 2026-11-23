"""Find the NAS by name (NFEAT-8): <name>.local on the home network, in Finder and Windows.

The responder (mdns_responder.py) needs the host's network to reach the LAN's multicast, which the
app's own container doesn't have, so it runs in a small container of its own on the host network,
made from the app's image (D17). This module starts, updates and removes that container and keeps
the setting: off until the person turns it on and confirms (the Docker guard lets a container on
the host's network through only then; the yes is remembered, so an update or a rename can make it
again), the name, and the names the NAS had before.

The rebrand: DEFAULT_NAME is the one place the product's name is used. A saved name from before the
Kiboto rebrand becomes the new default and no longer answers. A name the family changes in the
settings keeps answering, so their bookmarks, saved shares and Finder favourites keep working.
"""

import hashlib
import json
import os
import re
import socket
import sys
import threading
from typing import Any

from backend import legacy_names, product, runtime
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

DEFAULT_NAME = "kiboto"
DEFAULT_LABEL = "Kiboto"  # how Finder lists the NAS when it has the default name
PREVIOUS_NAMES: tuple[str, ...] = ()  # product names that still answer (none since the old one was dropped)
KEEP_OLD = 3  # names the family used before that still answer
CONTAINER = "kiboto-name"
RESPONDER = "/app/backend/services/mdns_responder.py"
UNIT = "kiboto-name.service"  # the same responder as a service, on a machine set up for Kiboto
STATE_FILE = os.path.join(DATA_DIR, "nas_name.json")
ELEVATED = {"X-Kiboto-Elevated": "1"}
_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_lock = threading.Lock()
NO_DOCKER = "Docker is not reachable, so the name can't be announced."


def valid(name: str) -> bool:
    return bool(_NAME.match(name or ""))


def config() -> dict[str, Any]:
    """{enabled, name, previous}: what is saved, else off with the default name (or KIBOTO_NAS_NAME)."""
    from backend import settings

    data = read_json(STATE_FILE, {})
    data = data if isinstance(data, dict) else {}
    name = str(data.get("name") or settings.current("nas_name") or DEFAULT_NAME).lower()
    if name == legacy_names.OLD_NAS_NAME:
        name = DEFAULT_NAME  # the default saved before the rebrand becomes the new one
    previous = [
        p for p in data.get("previous", []) if isinstance(p, str) and valid(p) and p != legacy_names.OLD_NAS_NAME
    ]
    return {
        # a guest stays silent until asked; a machine set up for Kiboto is found by name from the start
        "enabled": bool(data.get("enabled", runtime.managed_host())),
        "name": name if valid(name) else DEFAULT_NAME,
        "previous": previous,
        # a first NAS whose second one took over keeps its setting, and is silent until taken back
        "held": bool(data.get("held", False)),
    }


def answering_names(cfg: dict[str, Any]) -> list[str]:
    """The name first, then the names it had before (the family's and the product's)."""
    out: list[str] = []
    for n in [cfg["name"], *cfg.get("previous", []), *PREVIOUS_NAMES]:
        if valid(n) and n not in out:
            out.append(n)
    return out


def label(name: str) -> str:
    return DEFAULT_LABEL if name == DEFAULT_NAME else name


def save(enabled: bool | None = None, name: str | None = None) -> dict[str, Any]:
    """Changes the setting; a new name keeps the old one answering. Raises ValueError for a bad name."""
    with _lock:
        cfg = config()
        if name is not None:
            name = name.strip().lower().removesuffix(".local")
            if not valid(name):
                raise ValueError("Use letters, digits and dashes (up to 63), not starting or ending with a dash.")
            if name != cfg["name"]:
                cfg["previous"] = [cfg["name"], *[p for p in cfg["previous"] if p not in (cfg["name"], name)]][
                    :KEEP_OLD
                ]
                cfg["name"] = name
        if enabled is not None:
            cfg["enabled"] = bool(enabled)
        atomic_write_json(STATE_FILE, cfg)
    return ensure()


def hold(on: bool) -> dict[str, Any]:
    """High availability: a first NAS whose second one took over does not answer to its name
    (two boxes would), until the name is taken back. The setting itself stays as it is."""
    with _lock:
        cfg = config()
        cfg["held"] = bool(on)
        atomic_write_json(STATE_FILE, cfg)
    return ensure()


def give_up(name: str, back_to: str, enabled: bool) -> dict[str, Any]:
    """High availability: a second NAS that took over stops answering to the first one's name, for
    good (not kept among the names it had before), and is called what it was called."""
    with _lock:
        cfg = config()
        cfg["previous"] = [p for p in cfg["previous"] if p not in (name, back_to)]
        if cfg["name"] == name:
            cfg["name"] = back_to if valid(back_to) else DEFAULT_NAME
            cfg["enabled"] = bool(enabled)
        atomic_write_json(STATE_FILE, cfg)
    return ensure()


# --- the container ---------------------------------------------------------------------------------
def _docker(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, Any]:
    from backend.services.container_mutator import docker_request

    try:
        return docker_request(method, path, body=body, headers=headers)
    except (OSError, RuntimeError):  # no Docker socket (or it refused): the same as no answer
        logger.debug("[NasName] Docker did not answer %s %s", method, path, exc_info=True)
        return 0, None


def _self() -> dict[str, Any]:
    for ref in runtime.own_container_refs():
        code, info = _docker("GET", f"/containers/{ref}/json")
        if code == 200 and isinstance(info, dict):
            return info
    return {}


def web_port(me: dict[str, Any]) -> int:
    """The port the web page has on the host: the app's own when it shares the host's network, else
    the host port published for it."""
    from backend import settings

    inner = int(settings.current("port") or 8082)
    host_cfg = me.get("HostConfig") or {}
    if host_cfg.get("NetworkMode") == "host":
        return inner
    for binding in (host_cfg.get("PortBindings") or {}).get(f"{inner}/tcp") or []:
        if str(binding.get("HostPort") or "").isdigit():
            return int(binding["HostPort"])
    return inner


def timemachine_shares() -> list[str]:
    """Kiboto's own Time Machine shares, while its own Samba serves them: its container, or on a
    machine Kiboto runs the machine's own smbd (there is no container there, and the shares were
    never announced to Macs). A host's Samba (Unraid's, TrueNAS's) announces its own."""
    from backend.services import samba_host
    from backend.services.samba_engine import get_samba_engine

    engine = get_samba_engine()
    serving = samba_host.running() if samba_host.active() else engine.check_sidecar().get("state") == "running"
    if not serving:
        return []
    return sorted(s.name for s in engine.list_shares() if s.timemachine)


def serves_windows() -> bool:
    """Whether this box should answer Windows' own search (PCs then list it under Network): only
    where Kiboto serves the files over SMB itself. A host with its own file server (Unraid) has
    its own answerer, and two would fight over one port."""
    from backend.hardware.pal_storage import get_storage_platform

    try:
        return bool(get_storage_platform().get_capabilities().can_manage_shares)
    except (OSError, RuntimeError, ValueError, AttributeError):
        return False


def device_seed() -> str:
    """What this box's address for Windows is made from: its data folder's own mark, so the same
    box keeps the same address, and a second box with the same name is another device."""
    from backend.config import DATA_DIR
    from backend.fsutil import DATA_MARKER

    try:
        with open(os.path.join(DATA_DIR, DATA_MARKER), encoding="utf-8") as f:
            return f.read().strip()[:80]
    except OSError:
        return ""


def responder_args(cfg: dict[str, Any], port: int) -> list[str]:
    """What the responder is told: the names, the web page's port, the backup disks, Windows."""
    names = answering_names(cfg)
    args = ["--names", ",".join(names), "--label", label(cfg["name"]), "--http-port", str(port)]
    for share in timemachine_shares():
        args += ["--timemachine", share]
    if serves_windows():
        args += ["--windows", "--workgroup", "WORKGROUP", "--device", device_seed() or names[0]]
    return args


def desired(me: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """The container: the app's image, the responder, the host's network, nothing mounted."""
    cmd = [RESPONDER, *responder_args(cfg, web_port(me))]
    image = (me.get("Config") or {}).get("Image") or product.IMAGE + ":latest"
    want: dict[str, Any] = {
        "Image": image,
        "Entrypoint": ["python3"],
        "Cmd": cmd,
        "Healthcheck": {"Test": ["NONE"]},  # the image's own check asks the web app, which isn't here
        "HostConfig": {"NetworkMode": "host", "RestartPolicy": {"Name": "unless-stopped"}, "ReadonlyRootfs": True},
    }
    fingerprint = hashlib.sha256(json.dumps(want, sort_keys=True).encode()).hexdigest()[:16]
    want["Labels"] = {"app": CONTAINER, "managed-by": product.CONTAINER, "kiboto.config": fingerprint}
    return want


def refresh() -> None:
    """After a share change: the name service announces the Time Machine shares there are now."""
    if config()["enabled"]:
        threading.Thread(target=ensure, name="nas-name-refresh", daemon=True).start()


def _remove() -> None:
    _docker("POST", f"/containers/{CONTAINER}/stop?t=3")  # it says goodbye, so devices drop the name at once
    _docker("DELETE", f"/containers/{CONTAINER}?force=true")


def _remove_old_container() -> None:
    """The responder made before the rebrand (zettnas-name) goes, so only one container answers."""
    old = legacy_names.OLD_NAME_CONTAINER
    code, _ = _docker("GET", f"/containers/{old}/json")
    if code == 200:
        _docker("POST", f"/containers/{old}/stop?t=3")
        _docker("DELETE", f"/containers/{old}?force=true")
        logger.info("[NasName] Removed %s, the name service from before the rebrand", old)


# --- as a service of the machine ---------------------------------------------------------------------
def _own_port() -> int:
    from backend import settings

    return int(settings.current("port") or 8082)


def _unit(*args: str) -> tuple[int, str]:
    from backend.services.host_basics import run

    return run(["systemctl", *args])


def _unit_running() -> bool:
    return _unit("is-active", UNIT)[1] == "active"


def service_command(cfg: dict[str, Any]) -> list[str]:
    """The responder as a short-lived user of its own that can write nowhere: it only answers
    name lookups. It is restarted when it ends, and made again at every start of Kiboto."""
    here = os.path.join(os.path.dirname(os.path.realpath(__file__)), "mdns_responder.py")
    responder = [sys.executable, here, *responder_args(cfg, _own_port())]
    mark = hashlib.sha256(json.dumps(responder).encode()).hexdigest()[:16]
    return [
        "systemd-run",
        "--quiet",
        "--collect",
        "--unit",
        UNIT,
        "--description",
        f"Kiboto name service {mark}",
        *[x for prop in SERVICE_LIMITS for x in ("-p", prop)],
        *responder,
    ]


SERVICE_LIMITS = (
    "Restart=always",
    "RestartSec=5",
    "DynamicUser=yes",
    "ProtectSystem=strict",
    "ProtectHome=yes",
    "PrivateTmp=yes",
    "PrivateDevices=yes",
    "NoNewPrivileges=yes",
)


def _ensure_service(cfg: dict[str, Any]) -> dict[str, Any]:
    """On a machine set up for Kiboto: the unit matches the setting, and the machine has the name."""
    from backend.services import host_basics

    port = _own_port()
    running = _unit_running()
    if not cfg["enabled"] or cfg["held"]:
        if running:
            _unit("stop", UNIT)
            logger.info("[NasName] %s; %s stopped", "Held back" if cfg["held"] else "Turned off", UNIT)
        return status(cfg, running=False, port=port)
    host_basics.set_host_name(cfg["name"])
    cmd = service_command(cfg)
    described = cmd[cmd.index("--description") + 1]
    if running and _unit("show", UNIT, "-p", "Description", "--value")[1] == described:
        return status(cfg, running=True, port=port)
    _unit("stop", UNIT)
    _unit("reset-failed", UNIT)
    code, said = host_basics.run(cmd)
    if code != 0:
        logger.warning("[NasName] %s could not be started: %s", UNIT, said)
        return status(cfg, running=False, port=port, error="The name service could not be started.")
    logger.info("[NasName] %s answers for %s", UNIT, ", ".join(f"{n}.local" for n in answering_names(cfg)))
    return status(cfg, running=True, port=port)


def ensure() -> dict[str, Any]:
    """Makes the container match the setting (started, recreated after an update or a rename, or
    removed) and says how it stands."""
    cfg = config()
    if runtime.managed_host():
        with _lock:
            return _ensure_service(cfg)
    with _lock:
        _remove_old_container()
        code, info = _docker("GET", f"/containers/{CONTAINER}/json")
        exists = code == 200 and isinstance(info, dict)
        if not cfg["enabled"] or cfg["held"]:
            if exists:
                _remove()
                logger.info("[NasName] %s; %s removed", "Held back" if cfg["held"] else "Turned off", CONTAINER)
            return status(cfg, running=False)
        me = _self()
        if not me:
            return status(cfg, running=False, error=NO_DOCKER)
        want = desired(me, cfg)
        if exists:
            same = (info.get("Config") or {}).get("Labels", {}).get("kiboto.config") == want["Labels"]["kiboto.config"]
            running = bool((info.get("State") or {}).get("Running"))
            if same and running:
                return status(cfg, running=True, port=web_port(me))
            if same:
                start, _ = _docker("POST", f"/containers/{CONTAINER}/start")
                return status(cfg, running=start in (200, 204, 304), port=web_port(me))
            _remove()
        # the host's network: the person said yes when turning it on (Docker guard, ELEVATED)
        created, resp = _docker("POST", f"/containers/create?name={CONTAINER}", want, ELEVATED)
        if created not in (200, 201):
            logger.warning("[NasName] Could not create %s: %s %s", CONTAINER, created, resp)
            return status(cfg, running=False, error="The name service could not be started.")
        started, _ = _docker("POST", f"/containers/{CONTAINER}/start")
        logger.info("[NasName] %s answers for %s", CONTAINER, ", ".join(f"{n}.local" for n in answering_names(cfg)))
        return status(cfg, running=started in (200, 204, 304), port=web_port(me))


def status(
    cfg: dict[str, Any] | None = None, running: bool | None = None, port: int | None = None, error: str = ""
) -> dict[str, Any]:
    cfg = cfg or config()
    if runtime.managed_host():
        running = _unit_running() if running is None else running
        port = _own_port() if port is None else port
    if running is None:
        code, info = _docker("GET", f"/containers/{CONTAINER}/json")
        running = code == 200 and bool(((info or {}).get("State") or {}).get("Running"))
        if code == 0 and cfg["enabled"]:
            error = error or NO_DOCKER
    if port is None:
        port = web_port(_self())
    host = f"{cfg['name']}.local"
    return {
        "enabled": cfg["enabled"],
        "name": cfg["name"],
        "held": cfg["held"],
        "also_answers": answering_names(cfg)[1:],
        "windows": serves_windows(),  # Windows PCs list it under Network too
        "running": running,
        "address": host,
        "url": f"http://{host}" + ("" if port == 80 else f":{port}"),
        "error": error,
    }


def ensure_soon() -> None:
    """At startup, on a thread: the app's image may have changed with an update."""

    def run() -> None:
        try:
            ensure()
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("[NasName] Could not check the name service", exc_info=True)

    threading.Thread(target=run, name="nas-name", daemon=True).start()
