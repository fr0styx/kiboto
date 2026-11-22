"""The kernel, ZFS and Docker of a machine set up for Kiboto: held, and moved with Kiboto.

Debian updates everything else through apt as on any Debian. These three are held
(packaging/install.sh), because a new kernel that ZFS has not been built for comes up without the
pools, and a new Docker can change how apps run. Each Kiboto release carries the versions it was
tested with (packaging/host-set.json). When the machine's versions differ and Debian offers exactly
the tested ones, Updates offers to bring them there. Never past them: a version Debian offers that
no release was tested with waits.

The move runs as a unit of its own (apt takes minutes): the held packages are let go, the tested
versions installed, held again, and it is checked that ZFS is built for every installed kernel
before a restart is suggested. Docker keeps the apps running across its own restart
(live-restore in /etc/docker/daemon.json).

`run` is the command runner; tests hand in their own."""

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

from backend import runtime
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

PACKAGES = ("linux-image-amd64", "linux-headers-amd64", "zfs-dkms", "zfsutils-linux", "docker.io")
GROUPS = {"kernel": PACKAGES[:2], "zfs": PACKAGES[2:4], "docker": PACKAGES[4:]}
UNIT = "kiboto-host-set"
REBOOT_FLAG = "/run/reboot-required"
MODULES = "/lib/modules"
_VERSION = re.compile(r"^[0-9A-Za-z.+~:-]{1,64}$")
Run = Callable[..., tuple[int, str]]


def run(cmd: list[str], timeout: float = 60) -> tuple[int, str]:
    try:
        done = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
        )
        return done.returncode, ((done.stdout or "") + (done.stderr or "")).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def _result_file() -> str:
    return os.path.join(DATA_DIR, "host_set_result.json")


def tested_with(root: str = "") -> dict[str, str]:
    """The versions this release was tested with: {package: version}. {} when it says nothing."""
    root = root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    try:
        with open(os.path.join(root, "packaging", "host-set.json"), encoding="utf-8") as f:
            said = json.load(f).get("tested_with") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    return {p: v for p, v in said.items() if p in PACKAGES and isinstance(v, str) and _VERSION.match(v)}


def versions(do: Run) -> dict[str, dict[str, Any]]:
    """Per package what is installed, what apt would take by itself, and every version Debian
    offers (from the lists apt has now; Debian keeps several, e.g. the point release and backports)."""
    out = {}
    for pkg in PACKAGES:
        code, installed = do(["dpkg-query", "-W", "-f=${Version}", pkg])
        _, policy = do(["apt-cache", "policy", pkg])
        offered = re.search(r"^\s*Candidate:\s*(\S+)", policy, re.M)
        _, madison = do(["apt-cache", "madison", pkg])
        available = []
        for line in madison.splitlines():
            parts = [x.strip() for x in line.split("|")]
            if len(parts) == 3 and parts[0] == pkg and parts[2].endswith("Packages") and parts[1] not in available:
                available.append(parts[1])
        out[pkg] = {
            "installed": installed.strip() if code == 0 else "",
            "offered": offered.group(1) if offered and offered.group(1) != "(none)" else "",
            "available": available,
        }
    return out


def lower(do: Run) -> Callable[[str, str], bool]:
    """a < b as Debian orders versions."""
    return lambda a, b: do(["dpkg", "--compare-versions", a, "lt", b])[0] == 0


def plan(found: dict[str, dict[str, Any]], tested: dict[str, str], older: Callable[[str, str], bool]) -> dict[str, Any]:
    """`move`: the tested version is on offer and newer than the installed one. `waiting`: Debian
    offers something newer than both, that no release was tested with yet. `ahead`: installed is
    already newer than tested (a fresh install takes what Debian has); it is left alone, never moved back."""
    move, waiting, ahead = [], [], []
    for pkg, v in found.items():
        want, have = tested.get(pkg, ""), v["installed"]
        if want and have and have != want:
            if not older(have, want):
                ahead.append(pkg)
            elif want in v.get("available", []):
                move.append(pkg)  # a tested version that is not on offer (yet) can only wait
        top = want if want and (not have or older(have, want)) else have
        if v["offered"] and top and older(top, v["offered"]):
            waiting.append(pkg)
    return {"move": move, "waiting": waiting, "ahead": ahead}


def busy(do: Run) -> bool:
    return do(["systemctl", "is-active", UNIT])[0] == 0


def status(do: Run | None = None) -> dict[str, Any]:
    """For the page. Where Kiboto is a guest only `managed: false`: these belong to the host."""
    do = do or run
    if not runtime.managed_host():
        return {"managed": False}
    tested = tested_with()
    found = versions(do)
    last = read_json(_result_file(), None) if os.path.exists(_result_file()) else None
    return {
        "managed": True,
        "tested": bool(tested),
        "packages": [
            {"name": p, "installed": found[p]["installed"], "offered": found[p]["offered"], "tested": tested.get(p, "")}
            for p in PACKAGES
        ],
        **plan(found, tested, lower(do)),
        "running": busy(do),
        "restart_needed": os.path.exists(REBOOT_FLAG),
        "last": last if isinstance(last, dict) else None,
    }


def check(do: Run | None = None) -> bool:
    """Asks Debian what it offers now (apt-get update). The person asked for it."""
    do = do or run
    return runtime.managed_host() and do(["apt-get", "update", "-qq"], timeout=300)[0] == 0


def start(do: Run | None = None) -> bool:
    """Hands the move to a unit of its own. False when there is nothing to move or one already runs."""
    do = do or run
    st = status(do)
    if not st.get("managed") or st["running"] or not st["move"]:
        return False
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    code, said = do(
        [
            "systemd-run",
            "--unit",
            UNIT,
            "--collect",
            "--quiet",
            f"--working-directory={here}",
            f"--setenv=DATA_DIR={DATA_DIR}",
            sys.executable,
            "-m",
            "backend.services.host_set",
            "apply",
        ],
        timeout=30,
    )
    if code != 0:
        logger.warning("[HostSet] The move could not be started: %s", said)
    return code == 0


def zfs_built_for_every_kernel(do: Run, modules: str = "") -> list[str]:
    """The installed kernels ZFS has no module for. A restart into one of them comes up without pools."""
    modules = modules or MODULES
    try:
        kernels = sorted(k for k in os.listdir(modules) if os.path.isdir(os.path.join(modules, k, "kernel")))
    except OSError:
        return []
    _, said = do(["dkms", "status", "zfs"])
    built = {m.group(1) for m in re.finditer(r"zfs/[^,]+, ([^,]+), [^:]+: installed", said)}
    return [k for k in kernels if k not in built]


def apply(do: Run | None = None) -> dict[str, Any]:
    """The unit's work. Moves the held packages to the tested versions and holds them again."""
    do = do or run
    tested = tested_with()
    moving = plan(versions(do), tested, lower(do))["move"]
    result: dict[str, Any] = {"at": time.time(), "moved": moving, "result": "nothing", "error": ""}
    if moving:
        do(["apt-mark", "unhold", *moving])
        code, said = do(
            ["apt-get", "install", "-y", "-qq", "--no-install-recommends", *[f"{p}={tested[p]}" for p in moving]],
            timeout=3600,
        )
        do(["apt-mark", "hold", *PACKAGES])  # held again whatever happened
        if code != 0:
            result.update(result="failed", error=said.splitlines()[-1][:300] if said else "apt-get failed")
        else:
            missing = zfs_built_for_every_kernel(do)
            if missing:
                result.update(
                    result="zfs_missing",
                    error="ZFS is not built for " + ", ".join(missing) + ". Do not restart into it.",
                )
            else:
                result["result"] = "moved"
    atomic_write_json(_result_file(), result)
    logger.info("[HostSet] %s: %s %s", result["result"], ", ".join(moving), result["error"])
    return result


def main(argv: list[str]) -> int:
    if argv[1:2] != ["apply"]:
        return 2
    return 0 if apply()["result"] in ("moved", "nothing") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
