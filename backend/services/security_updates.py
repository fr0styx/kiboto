"""Debian's security fixes on Kiboto OS, installed by themselves.

Debian's unattended-upgrades takes the fixes from Debian's security archive every day, the kernel
included. Kiboto never restarts the machine for them: the Updates page says when a restart finishes
one. A new kernel may only start once ZFS is built for it, so the kernel hook
(packaging/kiboto-kernel-zfs.sh) keeps the machine on the kernel it runs until then. ZFS and Docker
stay held and move with Kiboto releases (host_set). KIBOTO_SECURITY_UPDATES=0 turns it off.

`keep_current` runs as root at every start of the host door, from the running release's files."""

import os
import subprocess
from collections.abc import Callable
from typing import Any

from backend.config import logger

KERNEL = ("linux-image-amd64", "linux-headers-amd64")
APT_CONF = "/etc/apt/apt.conf.d/52kiboto-security"
HOOKS = ("/etc/kernel/postinst.d/zzz-kiboto-zfs", "/etc/kernel/header_postinst.d/zzz-kiboto-zfs")
GRUB_CONF = "/etc/default/grub.d/90-kiboto.cfg"
FLAG = "/etc/kiboto/kernel-without-zfs"
STAMP = "/var/lib/apt/periodic/unattended-upgrades-stamp"
OFF_TEXT = (
    "// Kiboto: KIBOTO_SECURITY_UPDATES=0, so Debian's security fixes are not installed by themselves.\n"
    'APT::Periodic::Unattended-Upgrade "0";\n'
)
Run = Callable[..., tuple[int, str]]


def on() -> bool:
    from backend.config import SETTINGS

    return bool(getattr(SETTINGS, "security_updates", True))


def _run(cmd: list[str], timeout: float = 300) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _write(path: str, text: str, mode: int) -> bool:
    """Writes text when the file says something else. True when it changed."""
    if os.path.isfile(path) and (os.stat(path).st_mode & 0o777) == mode:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    return True


def keep_current(rel: str, run: Run | None = None, root: str = "") -> list[str]:
    """Puts this release's apt settings, kernel hook and GRUB setting in place, and lets the kernel
    follow Debian (or holds it again, when turned off). Returns what changed."""
    run = run or _run
    if not os.path.isdir(root + "/etc/apt/apt.conf.d"):
        return []
    src = os.path.join(rel, "packaging")
    try:
        with open(os.path.join(src, "kiboto-security.apt.conf"), encoding="utf-8") as f:
            apt_text = f.read()
        with open(os.path.join(src, "kiboto-kernel-zfs.sh"), encoding="utf-8") as f:
            hook = f.read()
        with open(os.path.join(src, "kiboto-grub.cfg"), encoding="utf-8") as f:
            grub = f.read()
    except OSError:
        return []  # a release from before these files
    changed = []
    if _write(root + APT_CONF, apt_text if on() else OFF_TEXT, 0o644):
        changed.append(APT_CONF)
    # the hook protects any kernel install, also one made by hand with apt, so it stays when this is off
    for path in HOOKS:
        if _write(root + path, hook, 0o755):
            changed.append(path)
    if os.path.isdir(root + "/etc/default") and _write(root + GRUB_CONF, grub, 0o644):
        changed.append(GRUB_CONF)
        code, said = run(["update-grub"], timeout=300)
        if code != 0:
            logger.warning("[Security] update-grub failed: %s", said[-300:])
    code, said = run(["apt-mark", "showhold"], timeout=60)
    held = set(said.split()) if code == 0 else set()
    if on():
        moving = [k for k in KERNEL if k in held]
        if moving and run(["apt-mark", "unhold", *moving], timeout=60)[0] == 0:
            changed.append("kernel follows Debian")
    elif code == 0:
        moving = [k for k in KERNEL if k not in held]
        if moving and run(["apt-mark", "hold", *moving], timeout=60)[0] == 0:
            changed.append("kernel held")
    if changed:
        logger.info("[Security] %s", ", ".join(changed))
    return changed


def status(root: str = "") -> dict[str, Any]:
    """For the Updates page: on or off, when Debian last looked for fixes, and a new kernel that
    waits for ZFS (the machine keeps starting the one it runs)."""
    try:
        last: float | None = os.path.getmtime(root + STAMP)
    except OSError:
        last = None
    try:
        with open(root + FLAG, encoding="utf-8") as f:
            waiting = f.read(100).strip()
    except OSError:
        waiting = ""
    return {"on": on(), "last": last, "kernel_without_zfs": waiting}
