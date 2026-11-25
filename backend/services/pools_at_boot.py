"""Brings Kiboto's pools back at boot, before Docker and the file servers start (the unit
kiboto-pools.service): `python -m backend.services.pools_at_boot`. Debian imports a ZFS pool by itself;
nothing else mounts a btrfs or ext4 pool. Exit code 1 when a pool could not be brought back, so the
unit shows as failed; Kiboto itself still starts and lists that pool as missing."""

import subprocess
import sys

from backend.hardware.pal import pool_registry

# What bringing pools back runs, as root: nothing else, whatever a record says. The program that
# runs is this table's own name, never the caller's string.
_PROGRAMS = {name: name for name in ("zpool", "mount", "findmnt", "btrfs", "chattr", "blkid")}


def _run(cmd: list[str]) -> tuple[int, str, str]:
    program = _PROGRAMS.get(cmd[0]) if cmd else None
    if program is None:
        return 126, "", "not a program for bringing pools back"
    try:
        res = subprocess.run([program, *cmd[1:]], capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "Command timed out"
    return res.returncode, res.stdout.strip(), res.stderr.strip()


def bring_back() -> dict[str, str]:
    """bring_back_all as root, in this process: the boot unit, or the host door when Kiboto starts
    (the web user cannot import a pool or mount it; found by the OS audit's drill, where after a
    restore from the pools none came back)."""
    if not pool_registry.load():
        return {}
    return pool_registry.bring_back_all(_run)


def main() -> int:
    done = pool_registry.bring_back_all(_run)
    for name, why in done.items():
        print(f"{name}: {'there' if not why else 'NOT there: ' + why}")
    return 1 if any(done.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
