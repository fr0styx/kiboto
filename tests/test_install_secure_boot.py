"""install.sh stops at once when Secure Boot is on: the ZFS it builds would not load (found by the OS audit)."""

import os
import subprocess
from pathlib import Path

INSTALL = Path(__file__).resolve().parents[1] / "packaging" / "install.sh"
VAR = "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"


def _secure_boot(efivars) -> str:
    text = INSTALL.read_text(encoding="utf-8")
    fn = text[text.index("secure_boot_on() {") : text.index("}\n", text.index("secure_boot_on() {")) + 2]
    script = fn + "\nsecure_boot_on && echo on || echo off\n"
    env = {**os.environ, "KIBOTO_EFIVARS": str(efivars)}
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=env).stdout.strip()


def test_secure_boot_is_read_from_the_firmware_variable(tmp_path):
    assert _secure_boot(tmp_path) == "off"  # no variable: a BIOS machine, or no EFI
    (tmp_path / VAR).write_bytes(bytes([6, 0, 0, 0, 0]))
    assert _secure_boot(tmp_path) == "off"
    (tmp_path / VAR).write_bytes(bytes([6, 0, 0, 0, 1]))
    assert _secure_boot(tmp_path) == "on"


def test_the_install_stops_early_and_says_what_to_do():
    text = INSTALL.read_text(encoding="utf-8")
    check = text.index('KIBOTO_ALLOW_SECURE_BOOT:-}" != 1 ] && secure_boot_on')
    assert text.index("must_be_this_machine() {") < check < text.index("packages() {")
    assert "Turn Secure Boot off in the firmware settings" in text
