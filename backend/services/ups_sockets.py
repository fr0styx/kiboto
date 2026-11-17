"""The UPS sockets after a safe shutdown (SET-31, Power stage 5; Power finding about "comes back").

The old command was "load.off.delay": the UPS switched its sockets off and left them off, so the
NAS could not start again when the power came back. Its answer was never read either. Now Kiboto
asks the UPS (over NUT, the only connection that takes commands) for "shutdown.return": switch
the sockets off after a delay and back on when the mains returns, which is what lets a NAS set to
"Restore on AC power loss" start by itself. Before relying on it, Power can list the UPS's
commands and say whether it has that one.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

RETURN_CMD = "shutdown.return"
TIMEOUT = 3.0
Connect = Callable[[tuple[str, int], float], socket.socket]


def _target(cfg: dict[str, Any]) -> tuple[str, int, str]:
    return str(cfg.get("host") or "127.0.0.1"), int(cfg.get("port") or 3493), str(cfg.get("ups_name") or "ups")


def over_nut(cfg: dict[str, Any]) -> bool:
    return str(cfg.get("mode") or "") in ("nut_client", "nut") or int(cfg.get("port") or 0) == 3493


class _Line:
    """One NUT conversation: send a line, read the answer line."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.buf = ""

    def ask(self, text: str) -> str:
        self.sock.sendall(f"{text}\n".encode())
        return self.read()

    def read(self) -> str:
        while "\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("the UPS service closed the connection")
            self.buf += chunk.decode("utf-8", "replace")
        line, self.buf = self.buf.split("\n", 1)
        return line.strip()


def _session(cfg: dict[str, Any], connect: Connect) -> tuple[socket.socket, _Line]:
    host, port, _ = _target(cfg)
    sock = connect((host, port), TIMEOUT)
    sock.settimeout(TIMEOUT)
    line = _Line(sock)
    for word, key in (("USERNAME", "username"), ("PASSWORD", "password")):
        if cfg.get(key):
            answer = line.ask(f"{word} {cfg[key]}")
            if not answer.startswith("OK"):
                sock.close()
                raise PermissionError(f"the UPS service refused the {key}: {answer}")
    return sock, line


def check(cfg: dict[str, Any], connect: Connect = socket.create_connection) -> dict[str, Any]:
    """Whether this UPS can switch its sockets off and back on by itself: {ok, why}."""
    if not over_nut(cfg):
        return {"ok": False, "code": "not_nut", "why": "Only a UPS reached over the network (NUT) takes commands."}
    _, _, ups = _target(cfg)
    try:
        sock, line = _session(cfg, connect)
        with sock:
            answer = line.ask(f"LIST CMD {ups}")
            if not answer.startswith("BEGIN LIST CMD"):
                return {"ok": False, "code": "refused", "why": f"The UPS service answered: {answer}"}
            cmds = set()
            while True:
                row = line.read()
                if row.startswith("END LIST CMD"):
                    break
                parts = row.split()
                if len(parts) >= 3 and parts[0] == "CMD":
                    cmds.add(parts[2])
    except (OSError, ConnectionError, PermissionError) as e:
        return {"ok": False, "code": "unreachable", "why": f"The UPS service could not be asked: {e}"}
    if RETURN_CMD not in cmds:
        return {
            "ok": False,
            "code": "no_command",
            "why": "This UPS has no command to switch its sockets back on when the power returns.",
        }
    return {"ok": True, "code": "", "why": ""}


def send_return(cfg: dict[str, Any], connect: Connect = socket.create_connection) -> dict[str, Any]:
    """Asks the UPS for shutdown.return and reads its answer: {ok, why}."""
    if not over_nut(cfg):
        return {"ok": False, "code": "not_nut", "why": "Only a UPS reached over the network (NUT) takes commands."}
    _, _, ups = _target(cfg)
    try:
        sock, line = _session(cfg, connect)
        with sock:
            answer = line.ask(f"INSTCMD {ups} {RETURN_CMD}")
    except (OSError, ConnectionError, PermissionError) as e:
        return {"ok": False, "code": "unreachable", "why": f"The UPS service could not be asked: {e}"}
    if answer.startswith("OK"):
        logger.warning("[UPS] The UPS switches its sockets off now and back on when the power returns")
        return {"ok": True, "code": "", "why": ""}
    return {"ok": False, "code": "refused", "why": f"The UPS refused: {answer}"}
