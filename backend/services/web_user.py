"""Kiboto's web process as the unprivileged user `kiboto` (ADR 0006 step 9), on a machine Kiboto runs.

Off by default, and for now only for trying it out: everything that changes the machine goes
through the host door (steps 1 to 8), and running without root shows what still does not. Turned
on (as root, or by the door), it

- makes the system user `kiboto`, in the file server's group `users` (shared folders) and
  `dialout` (the front screen's serial port);
- gives it Kiboto's data folder, except the logs the door and the Docker proxy write, which stay
  root's so the web process cannot change what they recorded;
- lets it into the private homes with an access list, the others still out;
- writes a systemd drop-in that runs kiboto.service as that user with no new privileges and only
  the right to use the low ports (HTTPS on 443).

Turned off, the drop-in goes and Kiboto runs as root again at its next start; the user and the
owners stay, which root does not mind.

    python -m backend.services.web_user on|off|status
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from backend.config import DATA_DIR, logger

USER = "kiboto"
GROUPS = ("users", "dialout")
DROP_IN = "/etc/systemd/system/kiboto.service.d/web-user.conf"
ROOTS_LOGS = ("door-audit.log", "docker-proxy-audit.log")  # written by root, read by people
UNIT = f"""# ADR 0006 step 9: Kiboto's web process without root (backend/services/web_user.py)
[Service]
User={USER}
Group={USER}
SupplementaryGroups={" ".join(GROUPS)}
NoNewPrivileges=yes
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE
"""

Run = Callable[..., tuple[int, str]]


def run(cmd: list[str], timeout: float = 600) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def is_on(drop_in: str = DROP_IN) -> bool:
    return os.path.exists(drop_in)


def _homes() -> str:
    try:
        from backend import places

        return places.homes_root()
    except (OSError, ValueError, ImportError):
        return ""


def turn_on(do: Run | None = None, drop_in: str = DROP_IN, data_dir: str = DATA_DIR) -> list[str]:
    """Everything above; returns what could not be done (empty when all went well)."""
    do = do or run
    problems = []
    if do(["id", "-u", USER])[0] != 0:
        code, said = do(
            ["useradd", "--system", "--home-dir", data_dir, "--no-create-home", "--shell", "/usr/sbin/nologin", USER]
        )
        if code != 0:
            return [f"the user {USER} could not be made: {said.strip()[-200:]}"]
    for group in GROUPS:
        if do(["getent", "group", group])[0] == 0 and do(["usermod", "-aG", group, USER])[0] != 0:
            problems.append(f"{USER} is not in {group}")
    if do(["chown", "-R", f"{USER}:{USER}", data_dir])[0] != 0:
        problems.append(f"{data_dir} was not given to {USER}")
    for name in ROOTS_LOGS:
        path = os.path.join(data_dir, name)
        if os.path.exists(path):
            do(["chown", "root:root", path])
            do(["chmod", "644", path])
    homes = _homes()
    if homes and os.path.isdir(homes):
        for acl in ([f"u:{USER}:rwX"], ["-d", f"u:{USER}:rwX"]):
            if do(["setfacl", "-R", "-m", *acl, homes])[0] != 0:
                problems.append(f"{USER} could not be let into {homes} (setfacl)")
                break
    os.makedirs(os.path.dirname(drop_in), exist_ok=True)
    with open(drop_in + ".new", "w", encoding="utf-8") as f:
        f.write(UNIT)
    os.replace(drop_in + ".new", drop_in)
    do(["systemctl", "daemon-reload"], timeout=60)
    logger.warning("[WebUser] kiboto.service runs as %s from its next start", USER)
    return problems


def turn_off(do: Run | None = None, drop_in: str = DROP_IN) -> list[str]:
    do = do or run
    if os.path.exists(drop_in):
        os.remove(drop_in)
        do(["systemctl", "daemon-reload"], timeout=60)
        logger.warning("[WebUser] kiboto.service runs as root again from its next start")
    return []


def status(drop_in: str = DROP_IN) -> dict[str, Any]:
    return {"on": is_on(drop_in), "user": USER}


def main(argv: list[str]) -> int:
    what = argv[1] if len(argv) > 1 else "status"
    if what not in ("on", "off", "status"):
        print("usage: python -m backend.services.web_user on|off|status")
        return 2
    if what == "status":
        print(status())
        return 0
    problems = turn_on() if what == "on" else turn_off()
    for p in problems:
        print(p)
    print("restart Kiboto (systemctl restart kiboto) for it to take effect")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
