"""Reading a drive's health with smartctl, which opens the raw device.

As root Kiboto runs smartctl itself. Once the web process is the unprivileged user (ADR 0006
step 9) it cannot open a drive, and the host door reads it instead: only the read-only flags
below, and only a drive that is there. A hang is an exit code TIMED_OUT, as with run_bounded."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from collections.abc import Sequence

from backend.proc import TIMED_OUT, run_bounded

READ_FLAGS = {"-j", "-n", "standby", "-i", "-H", "-A", "-x"}
_TYPE = re.compile(r"^[a-z][a-z0-9_]{0,15}(,[a-z0-9_]{1,16})?$|^nvme,0x[0-9a-f]{1,8}$")


def run(args: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
    """`smartctl *args`, here or through the door."""
    from backend import door

    if os.geteuid() == 0:
        return _here(list(args), timeout)
    try:  # a door that cannot be reached means here, as door.via does; its refusal is a failed read
        got = door.via("disks.smartctl", _here_as_data, args=list(args), limit=float(timeout))
    except (RuntimeError, ValueError) as e:
        return subprocess.CompletedProcess(["smartctl", *args], 127, "", str(e))
    return subprocess.CompletedProcess(["smartctl", *args], int(got["code"]), str(got["out"]), str(got["err"]))


def _here(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    return run_bounded(["smartctl", *args], timeout=timeout, capture_output=True, text=True)


def _here_as_data(args: list[str], limit: float) -> dict[str, object]:
    r = _here(args, limit)
    return {"code": r.returncode, "out": r.stdout or "", "err": r.stderr or ""}


def checked(args: list[str]) -> list[str]:
    """`args` when they only read a drive: the flags above, one -d type, and a drive's device at
    the end. ValueError otherwise."""
    if not args or not all(type(a) is str for a in args):
        raise ValueError("smartctl's arguments")
    *flags, device = args
    i = 0
    while i < len(flags):
        if flags[i] == "-d" and i + 1 < len(flags) and _TYPE.match(flags[i + 1]):
            i += 2
            continue
        if flags[i] not in READ_FLAGS:
            raise ValueError(f"{flags[i][:20]} is not a read-only smartctl flag")
        i += 1
    real = os.path.realpath(device)
    try:
        is_drive = real.startswith("/dev/") and stat.S_ISBLK(os.stat(real).st_mode)
    except OSError:
        is_drive = False
    if not is_drive:
        raise ValueError("the last argument must be a drive")
    return args


def read_in_door(args: list[str], limit: float) -> dict[str, object]:
    """The door's side: smartctl with the checked arguments, its answer as data."""
    r = run_bounded(["smartctl", *checked(args)], timeout=min(max(limit, 1.0), 60.0), capture_output=True, text=True)
    return {"code": r.returncode, "out": r.stdout or "", "err": r.stderr or "", "timed_out": r.returncode == TIMED_OUT}
