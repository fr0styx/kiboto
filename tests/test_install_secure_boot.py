"""Secure Boot on Kiboto OS: ZFS is signed with the machine's own DKMS key, which the firmware learns
once at the screen. The install used to stop when Secure Boot was on (found by the OS audit); it now
queues the key under a one-time code and carries on."""

import os
import subprocess
from pathlib import Path

from backend.services import secure_boot

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
    assert secure_boot.on(str(tmp_path)) is True  # the same reading on Kiboto's side


def test_with_secure_boot_on_the_install_queues_the_key_and_carries_on():
    text = INSTALL.read_text(encoding="utf-8")
    assert "KIBOTO_ALLOW_SECURE_BOOT" not in text and "Turn Secure Boot off in the firmware settings (often" not in text
    packages = text[text.index("packages() {") : text.index("\n}\n", text.index("packages() {"))]
    assert "secure_boot_on || die" in packages and "secure_boot_key" in packages  # only then, not on a plain failure
    key = text[text.index("secure_boot_key() {") : text.index("\n}\n", text.index("secure_boot_key() {"))]
    assert "dkms generate_mok" in key and "mokutil --test-key" in key
    # the code is never typed into a prompt: mokutil takes a hash of it, and the code stays root's
    assert 'mokutil --generate-hash="$sb_code"' in key and "--hash-file" in key
    assert "umask 077" in key and "secure-boot-code" in key and 'rm -f "$ETC/secure-boot.hash"' in key
    assert "/etc/issue.d/kiboto-secure-boot.issue" in key and "Enroll MOK" in key
    assert "mokutil " in text.split("TOOLS=")[1].split("\n")[0] or "mokutil" in text.split('TOOLS="')[1][:40]


def test_kiboto_tells_where_secure_boot_stands_without_reading_the_code(tmp_path, monkeypatch):
    monkeypatch.setattr(secure_boot, "CODE", str(tmp_path / "secure-boot-code"))
    monkeypatch.setattr(secure_boot, "EFIVARS", str(tmp_path))
    assert secure_boot.status() == "off"
    (tmp_path / VAR).write_bytes(bytes([6, 0, 0, 0, 1]))
    assert secure_boot.status() == "on"
    (tmp_path / "secure-boot-code").write_text("12345678\n")
    os.chmod(tmp_path / "secure-boot-code", 0)  # root's only: Kiboto only sees that it is there
    assert secure_boot.status() == "waiting"


def test_once_the_firmware_knows_the_key_the_code_goes_and_zfs_loads(tmp_path, monkeypatch):
    code, issue = tmp_path / "secure-boot-code", tmp_path / "kiboto-secure-boot.issue"
    monkeypatch.setattr(secure_boot, "CODE", str(code))
    monkeypatch.setattr(secure_boot, "ISSUE", str(issue))
    ran = []
    answers = {"mokutil": (1, "/var/lib/dkms/mok.pub is not enrolled")}

    def run(cmd):
        ran.append(cmd)
        return answers.get(cmd[0], (0, ""))

    assert secure_boot.settle(run) is False and ran == []  # nothing waits: nothing asked
    code.write_text("12345678\n")
    issue.write_text("note")
    assert secure_boot.settle(run) is False and code.exists() and ["modprobe", "zfs"] not in ran
    answers["mokutil"] = (0, "/var/lib/dkms/mok.pub is already enrolled")
    assert secure_boot.settle(run) is True
    assert not code.exists() and not issue.exists() and ["modprobe", "zfs"] in ran


def test_the_boot_unit_settles_secure_boot_before_the_pools_come_back():
    text = (Path(__file__).resolve().parents[1] / "backend" / "services" / "pools_at_boot.py").read_text()
    main = text[text.index("def main()") :]
    assert main.index("secure_boot.settle(") < main.index("bring_back_all")


def test_ci_installs_with_secure_boot_on_and_answers_the_key_manager():
    root = Path(__file__).resolve().parents[1]
    sh = (root / "scripts" / "os_install_check.sh").read_text()
    assert "OVMF_CODE_4M.secboot.fd" in sh and "OVMF_VARS_4M.ms.fd" in sh and "smm=on" in sh
    restart = sh[sh.index('stage "The same after a restart"') :]
    for words in ("Press any key to perform MOK management", "Enroll MOK", "Enroll the key", "Password", "Reboot"):
        assert words in restart
    # the code is read inside the machine and typed through the monitor, never printed
    assert 'sb_code=$($SSH "cat /etc/kiboto/secure-boot-code"' in restart and 'say "$sb_code' not in sh
    assert "mokutil --test-key /var/lib/dkms/mok.pub | grep -q 'already enrolled'" in sh
    import yaml

    job = yaml.safe_load((root / ".github" / "workflows" / "ci.yml").read_text())["jobs"]["os-secure-boot"]
    assert job["with"] == {"early": True, "fast": True, "secure_boot": True}


def test_the_boot_unit_hands_its_own_runner_to_secure_boot(monkeypatch):
    from backend.services import pools_at_boot

    seen = {}
    monkeypatch.setattr(secure_boot, "settle", lambda run: seen.setdefault("run", run))
    monkeypatch.setattr(pools_at_boot.pool_registry, "bring_back_all", lambda run: {})
    monkeypatch.setattr(pools_at_boot, "_run", lambda cmd: (0, "out of " + cmd[0], "err"))
    assert pools_at_boot.main() == 0
    assert seen["run"](["mokutil", "--test-key"]) == (0, "out of mokutil\nerr")
