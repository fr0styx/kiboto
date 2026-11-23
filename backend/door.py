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
from collections.abc import Callable
from typing import Any

SOCK = "/run/kiboto-door/door.sock"
IN_DOOR = "KIBOTO_IN_DOOR"  # set in the door process itself
MAX_REPLY = 1 << 20


class DoorError(RuntimeError):
    """The door refused or failed an operation; the message says why. `kind` is what the operation
    raised there ("value" for a refusal, "runtime" for a failure), `text` a refusal's words in the
    reader's language (SaidError), so the caller can raise the same kind of error here."""

    def __init__(self, message: str, kind: str = "", text: Any = None):
        super().__init__(message)
        self.kind, self.text = kind, text

    def as_error(self) -> Exception:
        if self.kind == "value":
            err = ValueError(str(self))
            err.text = self.text  # type: ignore[attr-defined]  # read as getattr(e, "text", None)
            return err
        if self.kind == "runtime":
            return RuntimeError(str(self))
        return self


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
    raise DoorError(str(reply.get("error") or "the door refused it"), str(reply.get("kind") or ""), reply.get("text"))


def via(op: str, here: Callable[..., Any], **args: Any) -> Any:
    """`op` in the door where it runs, else `here(**args)` in this process. A refusal or failure in
    the door comes back as the same kind of error; a door that does not answer means doing it
    here (the web process keeps root until the door has every operation, ADR 0006)."""
    if not available():
        return here(**args)
    try:
        return call(op, **args)
    except DoorError as e:
        if not e.kind and str(e).startswith("no such operation"):  # a door of the version before
            return here(**args)
        raise e.as_error() from None
    except OSError:
        return here(**args)
