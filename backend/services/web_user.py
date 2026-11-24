"""Kiboto's web process as the unprivileged user `kiboto` (ADR 0006 step 9), on a machine Kiboto runs.

Off by default, and for now only for trying it out: everything that changes the machine goes
through the host door (steps 1 to 8), and running without root shows what still does not. Turned
on (as root, or by the door), it

- makes the system user `kiboto`, in the file server's group `users` (shared folders),
  `dialout` (the front screen's serial port) and `kvm` (virtual machines);
- gives it Kiboto's data folder, except the logs the door and the Docker proxy write, which stay
  root's so the web process cannot change what they recorded;
- lets it into the private homes with an access list, the others still out, and into each
  pool's own folder (what it makes there, a Recycle Bin, stays open to it when it goes to the
  folder's owner) and the Recycle Bins already there;
- writes a systemd drop-in that runs kiboto.service as that user with no new privileges, no
  kernel modules, kernel settings or cgroups to change, no set-id files to make, and only the
  right to use the low ports (HTTPS on 443).

Turned off, the drop-in goes and Kiboto runs as root again at its next start; the user and the
owners stay, which root does not mind.

    python -m backend.services.web_user on|off|status
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Callable
from typing import Any

# nothing of Kiboto's at the top: importing its settings without DATA_DIR makes a data folder
# beside the code, and this is run by hand (main sets the service's folder first)
logger = logging.getLogger("Kiboto")
DATA = "/var/lib/kiboto"  # kiboto.service's DATA_DIR

USER = "kiboto"
GROUPS = ("users", "dialout", "kvm")  # shared folders, the front screen, virtual machines
DROP_IN = "/etc/systemd/system/kiboto.service.d/web-user.conf"
ROOTS_LOGS = ("door-audit.log", "docker-proxy-audit.log")  # written by root, read by people
ACL = f"u:{USER}:rwX"
BIN = ".RecycleBin"  # services/recycle_bin.BIN
UNIT = f"""# ADR 0006 step 9: Kiboto's web process without root (backend/services/web_user.py)
[Service]
User={USER}
Group={USER}
SupplementaryGroups={" ".join(GROUPS)}
NoNewPrivileges=yes
ProtectKernelModules=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
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


def _pool_roots() -> list[str]:
    try:
        from backend.hardware.pal import pool_registry

        return sorted({str(r.get("mountpoint") or "") for r in pool_registry.load()} - {""})
    except (OSError, ValueError, ImportError):
        return []


def _bins(root: str) -> list[str]:
    found = [os.path.join(root, BIN)] if os.path.isdir(os.path.join(root, BIN)) else []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return found
    return found + [os.path.join(root, n, BIN) for n in names if os.path.isdir(os.path.join(root, n, BIN))]


def _apps_root() -> str:
    try:
        from backend.services import apps_place

        return apps_place.root()[0]
    except (OSError, ValueError, ImportError):
        return ""


def _vm_folders(data_dir: str) -> list[str]:
    try:
        from backend.services import pool_places

        return sorted({pool_places.vms_root(data_dir), pool_places.iso_dir(data_dir)} - {""})
    except (OSError, ValueError, ImportError):
        return []


def _let_into_apps(do: Run, root: str) -> None:
    """The apps' folder, each app's folder and the files directly in it (its compose file and
    settings, which Kiboto writes); not the apps' own data further down."""
    if not root or not os.path.isdir(root):
        return
    _let_in(do, root)
    for name in sorted(os.listdir(root)):
        app = os.path.join(root, name)
        if not os.path.isdir(app) or os.path.islink(app):
            continue
        _let_in(do, app)
        for f in sorted(os.listdir(app)):
            path = os.path.join(app, f)
            if os.path.isfile(path) and not os.path.islink(path):
                do(["setfacl", "-m", ACL, path])


def _let_in(do: Run, folder: str, recursive: bool = False) -> bool:
    """An access list for the web user on `folder`: what is there, and what is made in it later."""
    deep = ["-R"] if recursive else []
    return all(do(["setfacl", *deep, *acl, folder])[0] == 0 for acl in (["-m", ACL], ["-d", "-m", ACL]))


def turn_on(do: Run | None = None, drop_in: str = DROP_IN, data_dir: str = "") -> list[str]:
    """Everything above; returns what could not be done (empty when all went well)."""
    do = do or run
    data_dir = data_dir or os.environ.get("DATA_DIR") or DATA
    if not os.path.isdir(data_dir):
        return [f"there is no data folder at {data_dir}"]
    problems = []
    if do(["id", "-u", USER])[0] != 0:
        code, said = do(
            ["useradd", "--system", "--home-dir", data_dir, "--no-create-home", "--shell", "/usr/sbin/nologin", USER]
        )
        if code != 0:
            return [f"the user {USER} could not be made: {said.strip()[-200:]}"]
    # its home is the data folder (Sigstore keeps its trust root there), also for a user made before
    if do(["usermod", "--home", data_dir, USER])[0] != 0:
        problems.append(f"the home of {USER} is not {data_dir}")
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
    if homes and os.path.isdir(homes) and not _let_in(do, homes, recursive=True):
        problems.append(f"{USER} could not be let into {homes} (setfacl)")
    for root in _pool_roots():
        if os.path.isdir(root) and not _let_in(do, root):
            problems.append(f"{USER} could not be let into {root} (setfacl)")
        for recycle in _bins(root):
            _let_in(do, recycle, recursive=True)
    _let_into_apps(do, _apps_root())
    for folder in _vm_folders(data_dir):  # a few large disk images: all of it
        if os.path.isdir(folder) and not _let_in(do, folder, recursive=True):
            problems.append(f"{USER} could not be let into {folder} (setfacl)")
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
    os.environ.setdefault("DATA_DIR", DATA)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    what = argv[1] if len(argv) > 1 else "status"
    if what not in ("on", "off", "status"):
        print("usage: python -m backend.services.web_user on|off|status")
        return 2
    if what == "status":
        print(status())
        return 0
    # Kiboto stopped first: running as root it would write files into the data folder after it
    # was handed over, and the new user could not open them
    run(["systemctl", "stop", "kiboto.service"], timeout=180)
    problems = turn_on() if what == "on" else turn_off()
    run(["systemctl", "start", "kiboto.service"], timeout=120)
    for p in problems:
        print(p)
    print("Kiboto was started again as " + (USER if what == "on" else "root"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
