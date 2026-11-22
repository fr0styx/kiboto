"""Where Kiboto runs.

In a container (on Unraid, TrueNAS or any Docker host) Kiboto is a guest: the host owns its pools,
its network and its power. Started as a process on the machine itself it is `native`. On a machine
that was set up for it (the install script leaves MANAGED_MARK) it is that machine's own interface,
the `managed host`, and may change what a guest must leave alone."""

import os

from backend.config import SETTINGS

# Docker and Podman leave these in a container; /app/backend is Kiboto's own image, for runtimes
# that leave neither. A native install lives elsewhere (/opt/kiboto).
CONTAINER_MARKS = ("/.dockerenv", "/run/.containerenv", "/app/backend")
MANAGED_MARK = "/etc/kiboto/managed"


def in_container() -> bool:
    return bool(SETTINGS.containerized) or any(os.path.exists(m) for m in CONTAINER_MARKS)


def native() -> bool:
    """Kiboto is a process of the machine itself, with no container around it."""
    return not in_container()


def managed_host() -> bool:
    """This machine was set up for Kiboto and Kiboto is its interface."""
    return native() and os.path.exists(MANAGED_MARK)


def own_container_hostname() -> str:
    """The start of Kiboto's own container id, as Docker sets it for the host name; "" when Kiboto runs
    natively. There the host name is the NAS's name (a name like "cafe" is also the start of container
    ids), and every container whose id began with it passed for Kiboto itself."""
    import socket

    return socket.gethostname() if in_container() else ""
