"""The first start of the install image waits for the network, and an apt-get update that reached no
server stops with a sentence about the network (found by the ISO run: ifupdown marks the network
online before DHCP answers, and the install stopped at "Unable to locate package zfs-dkms")."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = (ROOT / "packaging" / "install.sh").read_text(encoding="utf-8")
LATE = (ROOT / "packaging" / "image" / "late.sh").read_text(encoding="utf-8")


def test_the_first_start_waits_for_a_name_to_resolve_before_installing():
    run = LATE[LATE.index("<<'RUN'") : LATE.index("\nRUN\n")]
    wait = run.index("getent ahosts deb.debian.org")
    assert wait < run.index("sh /root/kiboto-install.sh")
    assert '[ "$i" -ge 60 ]' in run  # two minutes at most, then the install says what failed


def _check() -> str:
    body = INSTALL[INSTALL.index("packages() {") :]
    start = body.index('  if [ -n "$(missing zfs-dkms)" ]')
    return body[start : body.index("  fi\n", start) + 5]


def _run(tmp_path, policy: str, installed: bool) -> subprocess.CompletedProcess:
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "apt-cache").write_text(f"#!/bin/sh\nprintf '%s\\n' '{policy}'\n")
    (bin_ / "apt-cache").chmod(0o755)
    script = (
        'die() { echo "die: $*"; exit 1; }\n'
        + f"missing() {{ {'true' if installed else 'echo zfs-dkms'}; }}\n"
        + _check()
        + "echo went on\n"
    )
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}"}
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=env)


def test_no_zfs_candidate_stops_with_the_network_sentence(tmp_path):
    out = _run(tmp_path, "zfs-dkms:\n  Installed: (none)\n  Candidate: (none)", installed=False).stdout
    assert "die: Debian's package servers could not be reached" in out and "went on" not in out


def test_a_candidate_or_an_installed_zfs_goes_on(tmp_path):
    ok = _run(tmp_path, "zfs-dkms:\n  Installed: (none)\n  Candidate: 2.3.9-0+deb13u1", installed=False)
    assert ok.stdout.strip() == "went on"
    (tmp_path / "bin" / "apt-cache").unlink()
    (tmp_path / "bin").rmdir()
    held = _run(tmp_path, "Candidate: (none)", installed=True)  # a second run: ZFS is there and held
    assert held.stdout.strip() == "went on"


def test_the_check_comes_after_the_update_and_before_any_install():
    body = INSTALL[INSTALL.index("packages() {") :]
    assert body.index("apt-get update -qq") < body.index("Candidate: [0-9]") < body.index("apt-get install")
