"""Secure Boot on Kiboto OS.

ZFS is built on the machine and signed with the machine's own DKMS key. With Secure Boot on, the
installer queues that key for the firmware under a one-time code (packaging/install.sh,
secure_boot_key); at the next start the firmware's key manager asks the person at the screen to
enroll it. Until then ZFS cannot load and the pools wait.

`settle()` runs as root at every start (kiboto-pools.service): once the firmware knows the key it
removes the code and the note on the console, and loads ZFS so the pools come back in the same start.
`status()` tells the page where things stand, without reading the code (root's only).
"""

import glob
import os
from collections.abc import Callable

CODE = "/etc/kiboto/secure-boot-code"
ISSUE = "/etc/issue.d/kiboto-secure-boot.issue"
KEY = "/var/lib/dkms/mok.pub"
EFIVARS = "/sys/firmware/efi/efivars"
Run = Callable[[list[str]], tuple[int, str]]


def on(efivars: str | None = None) -> bool:
    """The firmware's own switch: the SecureBoot variable's last byte is 1 when it is on."""
    for path in glob.glob(os.path.join(efivars or EFIVARS, "SecureBoot-*")):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        return bool(data) and data[-1] == 1
    return False


def waiting() -> bool:
    """The key is queued and the step at the screen is not done yet."""
    return os.path.exists(CODE)


def status() -> str:
    """'waiting' (one step left at the screen), 'on', or 'off'."""
    if waiting():
        return "waiting"
    return "on" if on() else "off"


def settle(run: Run) -> bool:
    """As root at start: once the firmware knows the key, the code and the console note go, and ZFS
    loads for the pools that come back next. True when that happened in this start. `run` is the
    boot unit's own way to run a command (pools_at_boot), so this module starts no program itself."""
    if not waiting():
        return False
    code, said = run(["mokutil", "--test-key", KEY])
    if "already enrolled" not in said:
        return False
    for path in (CODE, ISSUE):
        if os.path.lexists(path):
            os.remove(path)
    run(["modprobe", "zfs"])
    print("Secure Boot: the firmware knows this machine's key; ZFS loads", flush=True)
    return True
