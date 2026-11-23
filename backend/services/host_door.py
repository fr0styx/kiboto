"""The host door (ADR 0006): a root service that changes the machine for Kiboto's web process.

It listens on a Unix socket (door.SOCK) and takes connections from root and the `kiboto` user
only (checked with SO_PEERCRED). Each request names one operation from OPERATIONS with its
arguments; anything else is refused: an unknown operation, a missing, extra or wrongly typed
argument. There is no shell and no free-form command: each operation is a function of Kiboto's
own that checks what it is given, as the API does. Every call is written to door-audit.log in
the data folder.

Run by kiboto-door.service on a machine Kiboto runs: `python -m backend.services.host_door`.
Until the web process gives up root (ADR 0006, the last step) it is used where it runs, and the
callers do the work themselves where it does not."""

from __future__ import annotations

import grp
import json
import os
import pwd
import socket
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend import door
from backend.config import DATA_DIR, logger

AUDIT = os.path.join(DATA_DIR, "door-audit.log")
MAX_REQUEST = 64 * 1024
USER = "kiboto"  # the user the web process will run as


@dataclass(frozen=True)
class Operation:
    run: Callable[..., Any]
    args: dict[str, type]  # every argument, required, with its type
    max_len: int = 256  # for text arguments


def _host(name: str) -> Callable[..., Any]:
    def run(**kw: Any) -> Any:
        from backend.services import host_basics

        return getattr(host_basics, name)(**kw)

    return run


OPERATIONS: dict[str, Operation] = {
    "door.ping": Operation(lambda: "pong", {}),
    "host.set_name": Operation(_host("set_host_name"), {"name": str}, max_len=63),
    "host.set_time_zone": Operation(_host("set_time_zone"), {"zone": str}, max_len=64),
    "host.set_clock_automatic": Operation(_host("set_clock_automatic"), {"on": bool}),
    "host.set_ssh": Operation(_host("set_ssh"), {"on": bool}),
}


def _checked(request: Any) -> tuple[Operation, dict[str, Any]]:
    """The operation and its arguments, or ValueError saying what is wrong with the request."""
    if not isinstance(request, dict) or not isinstance(request.get("op"), str):
        raise ValueError("not a request")
    op = OPERATIONS.get(request["op"])
    if op is None:
        raise ValueError(f"no such operation: {request['op'][:60]}")
    args = request.get("args") or {}
    if not isinstance(args, dict) or set(args) != set(op.args):
        raise ValueError(f"{request['op']} takes {', '.join(sorted(op.args)) or 'nothing'}")
    for name, kind in op.args.items():
        value = args[name]
        if type(value) is not kind:  # bool is not int, int is not bool
            raise ValueError(f"{name} must be {kind.__name__}")
        if kind is str and (len(value) > op.max_len or "\x00" in value):
            raise ValueError(f"{name} is too long")
    return op, args


def handle(request: Any, uid: int) -> dict[str, Any]:
    """One request from a caller with this uid, answered as {"ok", "result"} or {"ok", "error"}."""
    name = str(request.get("op"))[:60] if isinstance(request, dict) else "?"
    try:
        op, args = _checked(request)
    except ValueError as e:
        _audit(uid, name, "refused", str(e))
        return {"ok": False, "error": str(e)}
    try:
        result = op.run(**args)
    except (OSError, ValueError, RuntimeError, TypeError, LookupError) as e:  # told; the door keeps serving
        logger.warning("[Door] %s failed: %s", name, e)
        _audit(uid, name, "failed", str(e))
        return {"ok": False, "error": f"{name} failed: {e}"}
    _audit(uid, name, "done", "")
    return {"ok": True, "result": result}


def _audit(uid: int, op: str, outcome: str, why: str) -> None:
    line = json.dumps({"at": round(time.time()), "uid": uid, "op": op, "outcome": outcome, "why": why[:200]})
    try:
        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        logger.warning("[Door] the audit line was not written: %s", e)


def allowed_uids() -> set[int]:
    """Root, and the user the web process runs as once it has one."""
    uids = {0}
    try:
        uids.add(pwd.getpwnam(USER).pw_uid)
    except KeyError:
        logger.debug("[Door] no %s user yet: root only", USER)
    return uids


def peer_uid(conn: socket.socket) -> int:
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", creds)
    return uid


def _serve_one(conn: socket.socket, uids: set[int]) -> None:
    with conn:
        uid = peer_uid(conn)
        if uid not in uids:
            _audit(uid, "?", "refused", "not an allowed user")
            conn.sendall(b'{"ok": false, "error": "not allowed"}\n')
            return
        conn.settimeout(30)
        data = b""
        while not data.endswith(b"\n") and len(data) <= MAX_REQUEST:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        try:
            request = json.loads(data) if len(data) <= MAX_REQUEST else None
        except ValueError:
            request = None
        conn.sendall(json.dumps(handle(request, uid), default=str).encode() + b"\n")


def listen(path: str = door.SOCK) -> socket.socket:
    """The listening socket: only its owner and the web process's group may connect."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    try:
        os.chown(path, 0, grp.getgrnam(USER).gr_gid)
    except (KeyError, PermissionError):
        logger.debug("[Door] the socket stays root's alone")
    os.chmod(path, 0o660)
    server.listen(16)
    return server


def serve(path: str = door.SOCK, rounds: int | None = None) -> None:
    """Answers requests until stopped; `rounds` ends it after that many connections (tests)."""
    server = listen(path)
    uids = allowed_uids()
    logger.info("[Door] open on %s for uids %s", path, sorted(uids))
    with server:
        while rounds is None or rounds > 0:
            conn, _ = server.accept()
            threading.Thread(target=_serve_one, args=(conn, uids), daemon=True).start()
            rounds = None if rounds is None else rounds - 1


def main() -> int:
    os.environ[door.IN_DOOR] = "1"  # an operation run here does not ask the door again
    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
