"""Apps by their names, on a machine Kiboto runs on without a container.

Inside a container Kiboto shares a Docker network with the apps it talks to (its model servers, the
office suite, Frigate), and Docker answers for their names. As a service of the machine there is
nobody to answer: "kiboto-ai" means nothing to the machine. The machine can reach every container
by its address, though, so on a managed host Kiboto keeps the names and addresses of the running
containers in a marked block of /etc/hosts and brings it up to date as containers come and go.
A container on the host's own network is the machine itself (127.0.0.1)."""

import os
import re
import time
from typing import Any

from backend import runtime
from backend.config import logger
from backend.fsutil import atomic_write_text
from backend.services import docker_client

HOSTS = "/etc/hosts"
BEGIN = "# BEGIN KIBOTO APPS (written by Kiboto; changed by hand it is written again)"
END = "# END KIBOTO APPS"
EVERY_SECS = 15.0
_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$")


def addresses(containers: list[dict[str, Any]]) -> dict[str, str]:
    """{name: address} for running containers, from Docker's own list."""
    found: dict[str, str] = {}
    for c in containers:
        if str(c.get("State") or "").lower() != "running":
            continue
        nets = ((c.get("NetworkSettings") or {}).get("Networks") or {}) if isinstance(c, dict) else {}
        ip = "127.0.0.1" if "host" in nets else ""
        for _net, cfg in sorted(nets.items()):
            if not ip and isinstance(cfg, dict) and cfg.get("IPAddress"):
                ip = str(cfg["IPAddress"])
        for raw in c.get("Names") or []:
            name = str(raw).lstrip("/")
            if ip and _NAME.match(name):
                found[name] = ip
    return found


def with_block(text: str, names: dict[str, str]) -> str:
    """The hosts file with Kiboto's block replaced (or added at the end); every other line as it was."""
    lines = text.splitlines()
    if BEGIN in lines and END in lines and lines.index(BEGIN) < lines.index(END):
        lines = lines[: lines.index(BEGIN)] + lines[lines.index(END) + 1 :]
    while lines and not lines[-1].strip():
        lines.pop()
    if names:
        lines += ["", BEGIN, *[f"{ip}\t{name}" for name, ip in sorted(names.items())], END]
    return "\n".join(lines) + "\n"


def sync(hosts: str = HOSTS) -> bool:
    """Brings the block up to date. True when the file was written. Only on a managed host: the
    hosts file of any other machine is not Kiboto's to write."""
    if not runtime.managed_host():
        return False
    try:
        status, containers = docker_client.request("GET", "/containers/json", timeout=5.0)
    except docker_client.DockerUnavailable:
        return False  # Docker is down: the names that were known stay
    if status != 200 or not isinstance(containers, list):
        return False
    try:
        with open(hosts, encoding="utf-8") as f:
            have = f.read()
    except OSError:
        have = ""
    want = with_block(have, addresses(containers))
    if want == have:
        return False
    try:
        atomic_write_text(hosts, want)
        os.chmod(hosts, 0o644)
    except OSError as e:
        logger.warning("[Apps] The apps' names could not be written to %s: %s", hosts, e)
        return False
    return True


def keep_in_step(rounds: int | None = None) -> None:
    """Background loop on a managed host: the names follow the containers. `rounds` ends it (tests)."""
    while rounds is None or rounds > 0:
        try:
            sync()
        except (OSError, ValueError, RuntimeError):
            logger.warning("[Apps] The apps' names were not brought up to date", exc_info=True)
        time.sleep(EVERY_SECS)
        rounds = None if rounds is None else rounds - 1
