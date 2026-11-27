"""ZFS's module is installed before its tools: in one apt call dpkg may set up zfsutils-linux first,
and its zfs-load-module service fails on a module that is not built yet (seen on the install image's
first start)."""

from pathlib import Path

import pytest

TEXT = (Path(__file__).resolve().parents[1] / "packaging" / "install.sh").read_text(encoding="utf-8")


def _packages() -> str:
    start = TEXT.index("packages() {")
    return TEXT[start : TEXT.index("\n}\n", start)]


def test_the_module_comes_before_the_tools_one_call_each():
    body = _packages()
    assert "for pkg in zfs-dkms zfsutils-linux; do" in body
    assert "missing zfs-dkms zfsutils-linux" not in body
    loop = body[body.index("for pkg in zfs-dkms") : body.index("done", body.index("for pkg in zfs-dkms"))]
    installs = [ln for ln in loop.splitlines() if "apt-get install" in ln]
    assert len(installs) == 1 and all(ln.rstrip().endswith("$need >/dev/null") for ln in installs)
    assert 'missing "$pkg"' in loop
    assert "trixie-backports" not in loop  # Debian 13's own ZFS (2.3), whatever sources are listed


def test_a_failed_early_load_is_cleared_once_zfs_loads():
    body = _packages()
    assert body.index("if ! modprobe zfs") < body.index("systemctl reset-failed zfs-load-module.service")


@pytest.mark.parametrize("backports", [True, False])
def test_the_loop_asks_apt_for_the_real_package_names(tmp_path, backports):
    """Run the loop with the real missing() and a recording apt-get: a quoted "$need" once asked
    apt for "zfs-dkms " (missing() ends names with a space) and every fresh install stopped."""
    import os
    import subprocess

    body = _packages()
    loop = body[body.index("  for pkg in zfs-dkms") : body.index("  done", body.index("for pkg in zfs-dkms")) + 7]
    fn_start = TEXT.index("missing() {")
    missing = TEXT[fn_start : TEXT.index("\n}\n", fn_start) + 3]
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "apt.log"
    (bin_ / "apt-get").write_text(f'#!/bin/sh\nfor a in "$@"; do printf "[%s]" "$a"; done >> {log}\necho >> {log}\n')
    (bin_ / "dpkg").write_text("#!/bin/sh\nexit 1\n")  # nothing installed yet
    # are backports in the sources? (missing() greps too: that goes to the real grep)
    (bin_ / "grep").write_text(
        f'#!/bin/sh\ncase "$*" in *trixie-backports*) exit {0 if backports else 1};; esac\nexec /usr/bin/grep "$@"\n'
    )
    for f in bin_.iterdir():
        f.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:/usr/bin:/bin"}
    subprocess.run(["sh", "-c", missing + loop], check=True, env=env)
    calls = log.read_text().splitlines()
    assert len(calls) == 2
    assert "[trixie-backports]" not in calls[0]  # the same ZFS with or without backports listed
    assert calls[0].endswith("[zfs-dkms]") and calls[1].endswith("[zfsutils-linux]"), calls
