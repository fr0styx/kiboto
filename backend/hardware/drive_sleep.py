"""Let hard drives sleep after a while with nothing to do, on a machine set up for Kiboto.

A drive keeps its own sleep timer, set by `hdparm -S`; nothing in Kiboto has to watch the clock.
Only spinning drives that hold no part of the system get one (the system disk is written to all the
time and would only wake again). A drive that is asleep is left alone: setting the timer is a
command that would spin it up, and "never wake a sleeping drive" comes first. The timer lasts until
the drive loses power, so it is set again each time Kiboto starts, when the drives are awake.

On other hosts (Unraid, TrueNAS and the rest) the host's own spin-down setting decides."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from backend.hardware import power_state
from backend.proc import TIMED_OUT, run_bounded

CHOICES = (0, 10, 15, 20, 30, 60, 120, 180)  # minutes; 0 is off
SYSTEM_MOUNTS = ("/", "/boot", "/boot/efi", "/usr", "/var", "[SWAP]")
LSBLK = ["lsblk", "-J", "-o", "NAME,TYPE,ROTA,TRAN,MOUNTPOINTS"]

Run = Callable[[list[str]], tuple[int, str]]


def run(cmd: list[str]) -> tuple[int, str]:
    try:
        r = run_bounded(cmd, timeout=15, capture_output=True, text=True)
    except OSError as e:
        return 127, str(e)
    if r.returncode == TIMED_OUT:
        return 124, "timed out"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def timer_code(minutes: int) -> int:
    """hdparm -S's number: 1-240 count 5 seconds each, 241-251 count 30 minutes each, 0 is no timer."""
    if minutes <= 0:
        return 0
    if minutes <= 20:
        return minutes * 12
    return 240 + min(11, max(1, minutes // 30))


def _mounts(node: dict[str, Any]) -> list[str]:
    found = [m for m in (node.get("mountpoints") or []) if m]
    for child in node.get("children") or []:
        found += _mounts(child)
    return found


def spinning_drives(do: Run | None = None) -> list[str]:
    """The names (sdb) of the spinning data drives: rotating, not on USB, none of the system on them."""
    code, out = (do or run)(LSBLK)
    if code != 0:
        return []
    try:
        disks = json.loads(out).get("blockdevices") or []
    except ValueError:
        return []
    names = []
    for d in disks:
        if d.get("type") != "disk" or str(d.get("rota")).lower() not in ("true", "1"):
            continue
        if (d.get("tran") or "") == "usb" or any(m in SYSTEM_MOUNTS for m in _mounts(d)):
            continue
        names.append(str(d.get("name") or ""))
    return [n for n in names if n and not n.startswith(power_state.NEVER_SLEEP)]


def apply(minutes: int, do: Run | None = None, probe: Callable[[str], str] | None = None) -> list[dict[str, Any]]:
    """Sets every spinning data drive's timer to minutes (0 clears it). One row per drive: set,
    asleep (left alone) or failed, with what hdparm said."""
    do = do or run
    ask = probe or (lambda name: power_state.probe(name, max_age=0))
    rows = []
    for name in spinning_drives(do):
        if ask(name) == power_state.STANDBY:
            rows.append({"drive": name, "state": "asleep"})
            continue
        code, said = do(["hdparm", "-S", str(timer_code(minutes)), power_state.dev_path(name)])
        rows.append(
            {"drive": name, "state": "set" if code == 0 else "failed", "said": "" if code == 0 else said[-200:]}
        )
    return rows
