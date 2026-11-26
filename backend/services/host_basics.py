"""What the machine itself is called and what time it keeps.

In a container these belong to the host and Kiboto leaves them alone. On a machine set up for
Kiboto (runtime.managed_host) the name the family gave the NAS is the machine's own host name, and
the time zone chosen in Kiboto is the machine's, so its logs, its console and Kiboto agree.

`run` is the command runner; tests hand in their own."""

import os
import re
import socket
import subprocess
from collections.abc import Callable
from typing import Any

from backend import door, runtime, users_db
from backend.config import logger
from backend.fsutil import atomic_write_text

HOSTS = "/etc/hosts"
OWN_ADDRESS = "127.0.1.1"  # Debian's line for the machine's own name
_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_ZONE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+){0,2}$")
Run = Callable[..., tuple[int, str]]


def run(cmd: list[str], timeout: float = 20) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
        return done.returncode, (done.stdout or "").strip() or (done.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def host_name() -> str:
    return socket.gethostname()


def hosts_with_name(text: str, name: str) -> str:
    """/etc/hosts with the machine's own name on Debian's line for it, so the name resolves with
    no network. Every other line stays as it is."""
    line = f"{OWN_ADDRESS}\t{name}"
    out, done = [], False
    for row in text.splitlines():
        if row.split()[:1] == [OWN_ADDRESS]:
            if not done:
                out.append(line)
                done = True
            continue
        out.append(row)
    if not done:
        at = next((i + 1 for i, row in enumerate(out) if row.split()[:1] == ["127.0.0.1"]), 0)
        out.insert(at, line)
    return "\n".join(out) + "\n"


def _door(op: str, **args: Any) -> bool | None:
    """The host door's answer where it runs (ADR 0006); None to do it here: no door, or it did not
    answer (the web process is still root until the door has every operation)."""
    if not door.available():
        return None
    try:
        return bool(door.call(op, **args))
    except door.DoorError as e:
        logger.warning("[Machine] %s: %s", op, e)
        return False
    except OSError as e:
        logger.warning("[Machine] The host door did not answer (%s); doing %s here", e, op)
        return None


def set_host_name(name: str, do: Run | None = None, hosts: str = HOSTS) -> bool:
    """The machine takes the name. False where Kiboto is a guest, or when the machine refused."""
    if do is None and (via := _door("host.set_name", name=name)) is not None:
        return via
    do = do or run
    if not runtime.managed_host() or not _NAME.match(name or ""):
        return False
    if host_name() == name:
        return True
    code, said = do(["hostnamectl", "set-hostname", name])
    if code != 0:
        logger.warning("[Machine] The host name could not be set to %s: %s", name, said)
        return False
    try:
        with open(hosts, encoding="utf-8") as f:
            before = f.read()
        after = hosts_with_name(before, name)
        if after != before:
            atomic_write_text(hosts, after)
    except OSError as e:
        logger.warning("[Machine] %s could not be updated for the name %s: %s", hosts, name, e)
    logger.info("[Machine] This machine is now called %s", name)
    return True


def time_zone(link: str = "/etc/localtime") -> str:
    """The machine's time zone, read from where Debian keeps it. '' when it cannot be told."""
    try:
        target = os.path.realpath(link)
    except OSError:
        return ""
    _, found, zone = target.partition("/zoneinfo/")
    return zone if found and _ZONE.match(zone) else ""


def set_time_zone(zone: str, do: Run | None = None) -> bool:
    if do is None and (via := _door("host.set_time_zone", zone=zone)) is not None:
        return via
    do = do or run
    if not runtime.managed_host() or not _ZONE.match(zone or ""):
        return False
    if time_zone() == zone:
        return True
    code, said = do(["timedatectl", "set-timezone", zone])
    if code != 0:
        logger.warning("[Machine] The time zone could not be set to %s: %s", zone, said)
        return False
    logger.info("[Machine] This machine now keeps the time of %s", zone)
    return True


def _told(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def clock(do: Run | None = None) -> dict[str, bool]:
    """Whether the machine can set its clock from the internet, does, and is in step."""
    do = do or run
    code, said = do(["timedatectl", "show", "-p", "CanNTP", "-p", "NTP", "-p", "NTPSynchronized"])
    told = _told(said) if code == 0 else {}
    return {
        "can": told.get("CanNTP") == "yes",
        "automatic": told.get("NTP") == "yes",
        "in_step": told.get("NTPSynchronized") == "yes",
    }


def set_clock_automatic(on: bool, do: Run | None = None) -> bool:
    if do is None and (via := _door("host.set_clock_automatic", on=bool(on))) is not None:
        return via
    do = do or run
    if not runtime.managed_host():
        return False
    code, said = do(["timedatectl", "set-ntp", "true" if on else "false"])
    if code != 0:
        logger.warning("[Machine] Setting the clock from the internet could not be turned %s: %s", _word(on), said)
        return False
    logger.info("[Machine] Setting the clock from the internet is %s", _word(on))
    return True


SSHD = "/usr/sbin/sshd"
SSH_UNITS = ("ssh.service", "ssh.socket")  # Debian starts it as a service, or on demand by the socket
SSHD_DIR = "/etc/ssh/sshd_config.d"
IMAGE_SSH = "kiboto.conf"  # written by Kiboto's install image (packaging/image/late.sh): root may sign in
# sorts before the image's file: sshd takes the first value it reads for each setting
SIGN_IN_FILE = "00-kiboto-sign-in.conf"
SIGN_IN_TEXT = (
    "# Written by Kiboto at the first sign-in to its page: signing in over SSH takes a key, not a password.\n"
    "# Turn passwords back on in Kiboto (Network, This machine).\n"
    "PasswordAuthentication no\n"
    "KbdInteractiveAuthentication no\n"
    "PermitRootLogin prohibit-password\n"
)


def _word(on: bool) -> str:
    return "on" if on else "off"


def ssh(do: Run | None = None) -> dict[str, bool]:
    """Whether the machine has an SSH server and it takes sign-ins now."""
    do = do or run
    if not os.path.exists(SSHD):
        return {"installed": False, "on": False}
    _, said = do(["systemctl", "is-active", *SSH_UNITS])
    return {"installed": True, "on": any(line.strip() == "active" for line in said.splitlines())}


def set_ssh(on: bool, do: Run | None = None) -> bool:
    """Turns signing in over SSH on or off, now and at every start. Sessions that are open stay."""
    if do is None and (via := _door("host.set_ssh", on=bool(on))) is not None:
        return via
    do = do or run
    if not runtime.managed_host() or not os.path.exists(SSHD):
        return False
    cmd = ["systemctl", "enable", "--now", SSH_UNITS[0]] if on else ["systemctl", "disable", "--now", *SSH_UNITS]
    code, said = do(cmd)
    if code != 0:
        logger.warning("[Machine] SSH could not be turned %s: %s", _word(on), said)
        return False
    logger.info("[Machine] SSH is %s", _word(on))
    return True


def ssh_passwords() -> bool | None:
    """Whether a password signs in over SSH, on a machine installed from Kiboto's image; None
    elsewhere (someone who set up their own Debian keeps their own SSH settings)."""
    if not os.path.exists(os.path.join(SSHD_DIR, IMAGE_SSH)):
        return None
    return not os.path.exists(os.path.join(SSHD_DIR, SIGN_IN_FILE))


def set_ssh_passwords(on: bool, do: Run | None = None) -> bool:
    """Lets a password sign in over SSH again, or only a key. Sessions that are open stay."""
    if do is None and (via := _door("host.ssh_passwords", on=bool(on))) is not None:
        return via
    do = do or run
    if not runtime.managed_host() or ssh_passwords() is None:
        return False
    path = os.path.join(SSHD_DIR, SIGN_IN_FILE)
    if on:
        if os.path.exists(path):
            os.remove(path)
    else:
        with open(path + ".new", "w", encoding="utf-8") as f:
            f.write(SIGN_IN_TEXT)
        os.chmod(path + ".new", 0o644)  # sshd's own settings, as every file beside it
        os.replace(path + ".new", path)
    # a running sshd reads it again; one started by the socket reads it at each sign-in anyway
    do(["systemctl", "try-reload-or-restart", SSH_UNITS[0]])
    logger.info("[Machine] Signing in over SSH with a password is %s", _word(on))
    return True


def keys_only_after_first_sign_in(do: Run | None = None) -> bool:
    """Once, when the first sign-in to Kiboto's page is done: on a machine installed from Kiboto's image, the root password typed at the install no
    longer signs in over SSH. Keys still do, and the page has the switch to turn passwords back on."""
    if ssh_passwords() is not True:
        return False
    return set_ssh_passwords(False, do)


def status(do: Run | None = None) -> dict[str, Any]:
    """What the page shows. A guest says only that these belong to its host."""
    if not runtime.managed_host():
        return {"managed": False}
    return {
        "managed": True,
        "host_name": host_name(),
        "time_zone": time_zone(),
        "clock": clock(do),
        "ssh": ssh(do),
        "ssh_passwords": ssh_passwords(),
        "bridge": _bridge(),
        "system_disk": _system_disk(),
    }


def _system_disk() -> dict[str, Any]:
    from backend.hardware.pal import system_disk

    return system_disk.usage()


def _bridge() -> dict[str, Any]:
    """The bridge virtual machines join, where the machine's network is Kiboto's to change."""
    from backend.hardware.net import managed

    return {**managed.bridge_status(), "can": managed.networkd_runs()}


def restart_kiboto(delay: int = 2, do: Run | None = None) -> bool:
    """Kiboto is started again by the machine, a moment after the answer has left. False where
    Kiboto is a guest: there its container's restart policy decides. Through the host door where
    it runs: the web user may not ask systemd for it (the restore from the pools said so)."""
    if not runtime.managed_host():
        return False
    if do is None:
        from backend import door

        return bool(door.via("kiboto.restart", restart_here, delay=int(delay)))
    return restart_here(delay, do)


def restart_here(delay: int = 2, do: Run | None = None) -> bool:
    do = do or run
    delay = max(1, min(30, int(delay)))
    code, said = do(
        ["systemd-run", "--quiet", "--collect", f"--on-active={delay}", "systemctl", "restart", "kiboto.service"]
    )
    if code != 0:
        logger.warning("[Machine] Kiboto could not be restarted by the machine: %s", said)
    return code == 0


def _after_first_sign_in() -> None:
    keys_only_after_first_sign_in()


users_db.FIRST_SIGN_IN_LISTENERS.append(_after_first_sign_in)
