"""Samba as a service of the machine itself.

On Unraid and other hosts the host serves the files; on a Docker host Kiboto drives a Samba
container. On a machine set up for Kiboto (runtime.managed_host) the machine's own smbd serves them
and Kiboto drives it directly: /etc/samba/smb.conf says only "read Kiboto's settings", the accounts
are the machine's own users with the numbers Kiboto gave each person, and a change is applied by
reloading, closing the shared folders that changed and ending blocked addresses' connections.

`run` is the command runner; tests hand in their own."""

import os
import re
import subprocess
from collections.abc import Callable
from typing import Any

from backend import door, runtime
from backend.config import logger
from backend.settings import test_mode

ETC_CONF = "/etc/samba/smb.conf"
AUTH_LOG = "/var/log/samba/kiboto-auth.json"  # failed sign-ins, read by services/smb_signins.py
# "include", not "config file": with the latter Samba's own tools kept the default "private dir"
# while smbd took Kiboto's, so a password was stored where the server did not look.
POINTER = (
    "# Written by Kiboto. This machine's file server reads Kiboto's settings; change shared folders\n"
    "# in Kiboto. Debian's own file is kept beside this one as smb.conf.debian.\n"
    "[global]\n   include = {conf}\n"
)
Run = Callable[..., tuple[int, str, str]]
# what useradd, userdel and smbpasswd take as an account name. Kiboto's own usernames may start with
# a dash, which these tools read as an option: such a person gets no account of the machine.
ACCOUNT = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}$")


def _account_ok(name: str) -> bool:
    if ACCOUNT.fullmatch((name or "").lower()):
        return True
    logger.warning("[Samba] %r can't be an account of this machine, so it gets none", name)
    return False


def active() -> bool:
    return runtime.managed_host()


def run(cmd: list[str], feed: str | None = None, timeout: float = 20) -> tuple[int, str, str]:
    try:
        res = subprocess.run(cmd, input=feed, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]} did not answer"
    return res.returncode, res.stdout.strip(), res.stderr.strip()


_REAL_RUN = run


def _refuse(cmd: list[str], feed: str | None = None, timeout: float = 20) -> tuple[int, str, str]:
    return 1, "", "the test suite does not change this machine's accounts"


def _runner(do: "Run | None") -> "Run":
    """The tool runner to use. The test suite, run as root on a machine set up for Kiboto, made real
    system accounts through tests that make the host look managed: in test mode the real runner
    refuses unless a test passed or patched its own."""
    if do is not None:
        return do
    if run is _REAL_RUN and test_mode():
        return _refuse
    return run


def _through_door(op: str, here: Callable[..., Any], **args: Any) -> bool:
    """`op` in the host door where it runs (ADR 0006), else `here` in this process. A refusal there
    is said and answered False, as a failed run of the tool is."""
    try:
        return bool(door.via(op, here, **args))
    except (ValueError, RuntimeError) as e:
        logger.warning("[Samba] %s was refused: %s", op, e)
        return False


def global_lines(samba_dir: str) -> list[str]:
    """What the machine's smbd must be told that the container was given by its image: where the
    accounts are kept (in Kiboto's data folder, so they travel with a settings backup)."""
    return [
        f"   private dir = {os.path.join(samba_dir, 'private')}",
        "   passdb backend = tdbsam",
        # failed sign-ins (level 2: failures only) as JSON lines, read by services/smb_signins.py
        f"   log level = 0 auth_json_audit:2@{AUTH_LOG}",
    ]


def point_samba_here(conf: str, etc_conf: str = ETC_CONF, door_ok: bool = True) -> bool:
    """Makes /etc/samba/smb.conf read Kiboto's settings. True when the file was written. Through
    the host door where it runs; the door points it at its own copy of Kiboto's settings path."""
    if door_ok and etc_conf == ETC_CONF and door.available():
        return _through_door("samba.point_here", lambda: point_samba_here(conf, etc_conf, door_ok=False))
    want = POINTER.format(conf=conf)
    try:
        with open(etc_conf, encoding="utf-8") as f:
            have = f.read()
    except FileNotFoundError:
        have = None
    if have == want:
        return False
    os.makedirs(os.path.dirname(etc_conf), exist_ok=True)
    kept = etc_conf + ".debian"
    if have is not None and not os.path.exists(kept):
        os.replace(etc_conf, kept)
    with open(etc_conf, "w", encoding="utf-8") as f:
        f.write(want)
    return True


def ensure_accounts(numbers: dict[str, int], do: Run | None = None) -> None:
    """Each person as a user of the machine, with the number Kiboto gave them and no sign-in of
    their own: made, or made again when an older one had another number."""
    do = _runner(do)
    for name, want in numbers.items():
        if not _account_ok(name):
            continue
        code, have, _ = do(["id", "-u", name])
        if code == 0 and have.strip() == str(want):
            continue
        if code == 0:
            do(["userdel", name])
        code, _, err = do(["useradd", "-M", "-N", "-u", str(want), "-g", "users", "-s", "/usr/sbin/nologin", name])
        if code != 0:
            logger.warning("[Samba] The account of %s could not be made: %s", name, err)


def running(do: Run | None = None) -> bool:
    do = _runner(do)
    return do(["systemctl", "is-active", "--quiet", "smbd"])[0] == 0


def reload(changed: dict[str, Any] | None, numbers: dict[str, int], do: Run | None = None) -> bool:
    """Applies new settings. Samba gives reloaded settings to new connections only, so the shared
    folders whose section changed are closed and blocked addresses' connections ended; everyone
    else stays connected. A change it cannot tell apart (`changed` is None), a change to the private
    folders, or a server that is not running: the server starts again."""
    if do is None and door.available():
        return _through_door(
            "samba.reload", lambda changed, numbers: reload(changed, numbers, run), changed=changed, numbers=numbers
        )
    do = _runner(do)
    ensure_accounts(numbers, do)
    if changed is None or changed.get("homes") or not running(do):
        code, _, err = do(["systemctl", "restart", "smbd"], timeout=60)
        if code != 0:
            logger.error("[Samba] The file server did not start: %s", err)
        return code == 0
    if do(["smbcontrol", "all", "reload-config"])[0] != 0:
        return do(["systemctl", "restart", "smbd"], timeout=60)[0] == 0
    for share in changed.get("shares") or []:
        if not str(share).startswith("-"):
            do(["smbcontrol", "all", "close-share", share])
    for ip in changed.get("ips") or []:
        if not str(ip).startswith("-"):
            do(["smbcontrol", "all", "kill-client-ip", ip])
    return True


def set_password(name: str, number: int, password: str, do: Run | None = None) -> bool:
    if do is None and door.available():
        here = lambda name, number, password: set_password(name, number, password, run)  # noqa: E731
        return _through_door("samba.set_password", here, name=name, number=int(number), password=password)
    do = _runner(do)
    if not _account_ok(name.lower()):
        return False
    ensure_accounts({name.lower(): number}, do)
    code, _, err = do(["smbpasswd", "-s", "-a", name], feed=f"{password}\n{password}\n")
    if code != 0:
        logger.warning("[Samba] The network password of %s was not set: %s", name, err)
    return code == 0


def remove(name: str, do: Run | None = None) -> bool:
    if do is None and door.available():
        return _through_door("samba.remove", lambda name: remove(name, run), name=name)
    do = _runner(do)
    if not _account_ok(name):
        return False
    ok = do(["smbpasswd", "-x", name])[0] == 0
    do(["userdel", name])
    return ok


def set_enabled(name: str, enabled: bool, do: Run | None = None) -> bool:
    if do is None and door.available():
        here = lambda name, enabled: set_enabled(name, enabled, run)  # noqa: E731
        return _through_door("samba.set_enabled", here, name=name, enabled=bool(enabled))
    do = _runner(do)
    return _account_ok(name) and do(["smbpasswd", "-e" if enabled else "-d", name])[0] == 0
