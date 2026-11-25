"""ZFS's module is installed before its tools: in one apt call dpkg may set up zfsutils-linux first,
and its zfs-load-module service fails on a module that is not built yet (seen on the install image's
first start)."""

from pathlib import Path

TEXT = (Path(__file__).resolve().parents[1] / "packaging" / "install.sh").read_text(encoding="utf-8")


def _packages() -> str:
    start = TEXT.index("packages() {")
    return TEXT[start : TEXT.index("\n}\n", start)]


def test_the_module_comes_before_the_tools_one_call_each():
    body = _packages()
    assert "for pkg in zfs-dkms zfsutils-linux; do" in body
    assert "missing zfs-dkms zfsutils-linux" not in body
    loop = body[body.index("for pkg in zfs-dkms") : body.index("done", body.index("for pkg in zfs-dkms"))]
    assert (
        loop.count("apt-get install") == 2
        and sum('"$need"' in ln for ln in loop.splitlines() if "apt-get install" in ln) == 2
        and 'missing "$pkg"' in loop
    )
    assert "-t trixie-backports" in loop


def test_a_failed_early_load_is_cleared_once_zfs_loads():
    body = _packages()
    assert body.index("modprobe zfs || die") < body.index("systemctl reset-failed zfs-load-module.service")
