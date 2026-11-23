"""The host door's client (ADR 0006): how the rest of Kiboto asks for what changes the machine.

On a machine Kiboto runs, a separate root service (services/host_door.py, kiboto-door.service)
does the work the web process should not do itself, from a fixed list of operations. This module
only speaks to it: one JSON line out, one back, over a Unix socket. Where there is no door (a
container, the tests, a machine set up before it existed) `available()` is False and the caller
does the work itself, as before. Inside the door process it is False too, so an operation the door
runs does not ask the door again."""

from __future__ import annotations

import json
import os
import socket
from typing import Any

SOCK = "/run/kiboto-door/door.sock"
IN_DOOR = "KIBOTO_IN_DOOR"  # set in the door process itself
MAX_REPLY = 1 << 20


class DoorError(RuntimeError):
    """The door refused or failed an operation; the message says why."""


def inside() -> bool:
    return os.environ.get(IN_DOOR) == "1"


def available(sock: str = SOCK) -> bool:
    """Whether operations go through the door here."""
    return not inside() and os.path.exists(sock)


def call(op: str, *, timeout: float = 120, sock: str = SOCK, **args: Any) -> Any:
    """Runs one operation in the door and returns its result; DoorError when it was refused or
    failed, OSError when the door could not be reached."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(sock)
        s.sendall(json.dumps({"op": op, "args": args}).encode() + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
            if len(data) > MAX_REPLY:
                raise DoorError("the door's answer was too long")
    try:
        reply = json.loads(data or b"{}")
    except ValueError as e:
        raise DoorError("the door gave no answer") from e
    if reply.get("ok"):
        return reply.get("result")
    raise DoorError(str(reply.get("error") or "the door refused it"))
