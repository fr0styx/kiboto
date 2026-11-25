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


def is_root() -> bool:
    return not hasattr(os, "geteuid") or os.geteuid() == 0


def without_root() -> bool:
    """On a machine Kiboto runs, the web process is not root (ADR 0006). What still needs root and
    has no operation in the host door cannot be done there yet, and says so instead of failing."""
    return managed_host() and not is_root()


def own_container_hostname() -> str:
    """The start of Kiboto's own container id, as Docker sets it for the host name; "" when Kiboto runs
    natively. There the host name is the NAS's name (a name like "cafe" is also the start of container
    ids), and every container whose id began with it passed for Kiboto itself."""
    import socket

    return socket.gethostname() if in_container() else ""


def own_container_refs() -> tuple[str, ...]:
    """The names to look Kiboto's own container up by: its id start, then its names (an older one too).
    None natively, where there is no container of its own and the host name could be anyone's."""
    if not in_container():
        return ()
    from backend import legacy_names

    return (own_container_hostname(), *legacy_names.app_container_names())
