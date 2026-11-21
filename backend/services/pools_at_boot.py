"""Brings Kiboto's pools back at boot, before Docker and the file servers start (the unit
kiboto-pools.service): `python -m backend.services.pools_at_boot`. Debian imports a ZFS pool by itself;
nothing else mounts a btrfs or ext4 pool. Exit code 1 when a pool could not be brought back, so the
unit shows as failed; Kiboto itself still starts and lists that pool as missing."""

import subprocess
import sys

from backend.hardware.pal import pool_registry


def _run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "Command timed out"
    return res.returncode, res.stdout.strip(), res.stderr.strip()


def main() -> int:
    done = pool_registry.bring_back_all(_run)
    for name, why in done.items():
        print(f"{name}: {'there' if not why else 'NOT there: ' + why}")
    return 1 if any(done.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
