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
import time
from collections.abc import Callable
from typing import Any

SOCK = "/run/kiboto-door/door.sock"
DOCKER_SOCK = "/run/kiboto-door/docker.sock"  # the Docker allow-list proxy the door runs (ADR 0006 step 7)
IN_DOOR = "KIBOTO_IN_DOOR"  # set in the door process itself
MAX_REPLY = 1 << 20
LONG = {  # seconds an operation may take, where the default is too short
    "storage.create_pool": 900,
    "storage.import_pool": 900,
    "storage.export_pool": 600,
    "storage.erase_pool": 900,
    "storage.allow_changes": 600,
    "update.start": 900,  # downloads nothing (the image is there) but makes a Python environment
    "packages.add_missing": 1800,
    "packages.check": 360,
}


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


def call(op: str, *, timeout: float | None = None, sock: str = SOCK, **args: Any) -> Any:
    """Runs one operation in the door and returns its result; DoorError when it was refused or
    failed, OSError when the door could not be reached. Once the door has the request, losing
    it (a timeout, a door that stopped) is a DoorError too: the operation may be running."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout or LONG.get(op, 120))
        s.connect(sock)
        try:
            data = _exchange(s, json.dumps({"op": op, "args": args}).encode() + b"\n")
        except OSError as e:
            raise DoorError(f"the door did not finish answering ({e.__class__.__name__})", "runtime") from e
    try:
        reply = json.loads(data or b"{}")
    except ValueError as e:
        raise DoorError("the door gave no answer") from e
    if reply.get("ok"):
        return reply.get("result")
    raise DoorError(str(reply.get("error") or "the door refused it"), str(reply.get("kind") or ""), reply.get("text"))


def _exchange(s: socket.socket, request: bytes) -> bytes:
    s.sendall(request)
    data = b""
    while not data.endswith(b"\n"):
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
        if len(data) > MAX_REPLY:
            raise DoorError("the door's answer was too long")
    return data


def version(root: str = "") -> str:
    """Which code the door runs: the build, and the size and time of every file of the backend
    (the door runs many of them; a change without a new build, on a test machine, counts too). Only
    file facts are read, not the files. The door answers door.version with its own."""
    import hashlib

    from backend import settings

    root = root or os.path.dirname(os.path.abspath(__file__))
    facts = hashlib.sha256()
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(f for f in files if f.endswith(".py")):
            try:
                st = os.stat(os.path.join(folder, name))
            except OSError:
                continue
            facts.update(
                f"{os.path.relpath(os.path.join(folder, name), root)}:{st.st_size}:{st.st_mtime_ns}\n".encode()
            )
    return f"{settings.current('build_commit') or ''}:{facts.hexdigest()[:12]}"


def current(sock: str = SOCK) -> bool:
    """Whether the door that answers runs this same code; False when it does not answer."""
    try:
        return call("door.version", timeout=5, sock=sock) == version()
    except (OSError, DoorError):
        return False


def wait_open(timeout: float = 10.0, sock: str = SOCK) -> bool:
    """Whether the door answers within `timeout` seconds. Right after it was (re)started its socket
    comes a moment later, and an operation asked in that moment would be done here instead."""
    end = time.monotonic() + timeout
    while not _answers(sock):
        if time.monotonic() >= end:
            return False
        time.sleep(0.2)
    return True


def _answers(sock: str) -> bool:
    try:
        return call("door.ping", timeout=2, sock=sock) == "pong"
    except (OSError, DoorError):  # not open yet
        return False


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
