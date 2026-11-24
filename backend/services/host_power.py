"""Restarting or switching off the host, checked (SET-31, Power stage 4; Power finding A11).

The manual route ran the first command it found with Popen and said "dispatched" without looking
at the answer. Inside a container "reboot" and "poweroff" do not reach the host at all, and when
nothing worked it fell back to the kernel's emergency keys, which cut the power without stopping
anything. Now there is one list of commands that really act on the host, used by the Restart and
Shut down buttons and by the UPS shutdown alike; each is run and its answer read; and when there is
none the page says so before anything is stopped, instead of pretending.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any

from backend.settings import test_mode

logger = logging.getLogger(__name__)

# commands mounted from the host (docker-compose: /host/reboot, /host/powerdown) or the host's own
# (Unraid's /usr/local/sbin), then, only when Kiboto runs on the host itself, the system's
HOST_COMMANDS = {
    "reboot": ("/host/reboot", "/usr/local/sbin/reboot"),
    "shutdown": ("/host/powerdown", "/usr/local/sbin/powerdown"),
}
OWN_COMMANDS = {"reboot": ("reboot",), "shutdown": ("poweroff",)}
CONTAINER_MARK = "/.dockerenv"
WAIT_SECS = 20  # a command that is still running after this is taken as the host going down


def in_container() -> bool:
    return os.path.exists(CONTAINER_MARK)


def commands(action: str) -> list[str]:
    """The commands that restart ("reboot") or switch off ("shutdown") the host, best first."""
    if action not in HOST_COMMANDS:
        raise ValueError("action is reboot or shutdown")
    found = [p for p in HOST_COMMANDS[action] if os.path.exists(p) and os.access(p, os.X_OK)]
    if not in_container():
        found += [w for w in (shutil.which(n) for n in OWN_COMMANDS[action]) if w]
    return found


def can(action: str) -> dict[str, Any]:
    """Whether Kiboto can do it here, and if not, why (for the page, before anything is stopped)."""
    if test_mode():
        return {"ok": True, "how": "test", "why": ""}
    found = commands(action)
    if found:
        return {"ok": True, "how": found[0], "why": ""}
    name = "reboot" if action == "reboot" else "powerdown"
    if in_container():
        why = (
            f"Kiboto runs in a container and no host command is mounted. Mount the host's {name} command at "
            f"/host/{name}, or use the host's own menu."
        )
        text = {"msg_key": "srv.power_no_host_command", "params": {"name": name}}  # gitleaks:allow (a text key)
    else:
        why = "No restart or shut-down command was found on this system."
        text = {"msg_key": "srv.power_no_command", "params": {}}  # gitleaks:allow (a text key)
    # the sentence's key and values beside it, so the page shows it in the reader's language
    return {"ok": False, "how": "", "why": why, "text": text}


def run(action: str, cmds: list[str] | None = None) -> dict[str, Any]:
    """Runs the first command that answers (of cmds, or of commands(action)); {started, how, error}.
    Never the kernel's emergency keys. On a machine Kiboto runs the host door does it (ADR 0006),
    with its own list of commands."""
    if test_mode():
        logger.info("[Power] Test mode: %s not run", action)
        return {"started": True, "how": "test", "error": ""}
    from backend import door

    if action in HOST_COMMANDS and door.available():
        try:
            return dict(door.call("power.run", action=action))
        except door.DoorError as e:
            if str(e).startswith("the door did not finish"):  # it took the request: the machine is going down
                return {"started": True, "how": "door", "error": ""}
            return {"started": False, "how": "", "error": str(e)}
        except OSError:
            logger.debug("[Power] no door to ask; done here")
    return _run_here(action, cmds)


def _run_here(action: str, cmds: list[str] | None = None) -> dict[str, Any]:
    error = ""
    for cmd in commands(action) if cmds is None else cmds:
        try:
            res = subprocess.run([cmd], capture_output=True, text=True, timeout=WAIT_SECS)
        except subprocess.TimeoutExpired:
            logger.warning("[Power] %s is still running: the host is going down", cmd)
            return {"started": True, "how": cmd, "error": ""}
        except OSError as e:
            error = f"{cmd} could not be run ({e.strerror or e})"
            logger.error("[Power] %s", error)
            continue
        if res.returncode == 0:
            logger.critical("[Power] Host %s started with %s", action, cmd)
            return {"started": True, "how": cmd, "error": ""}
        error = f"{cmd} failed (exit {res.returncode})"
        logger.error("[Power] %s: %s", error, (res.stderr or "").strip()[:200])
    return {"started": False, "how": "", "error": error or can(action)["why"]}
