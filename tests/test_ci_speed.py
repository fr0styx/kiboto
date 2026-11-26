"""Faster shipping without weaker checks (26 Nov 2026): the Kiboto OS check can start from a disk
on which ZFS is already built, and a trial builds arm64 on arm64 runners. These keep the fast paths
from quietly testing less than the full ones."""

import os
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _wf(name):
    return yaml.safe_load(_read(".github", "workflows", name))


SCRIPT = _read("scripts", "os_install_check.sh")
INSTALL = _read("packaging", "install.sh")


def test_a_prepared_disk_replaces_only_the_fresh_debian():
    start = SCRIPT[SCRIPT.index('stage "A fresh Debian 13"') :]
    assert start.index('if [ -n "${KB_OS_PREPARED:-}" ]; then') < start.index("KB_OS_BASE")
    # the install and every check still run on it: only where the machine starts from differs
    rest = SCRIPT[SCRIPT.index('stage "Kiboto installs itself"') :]
    assert "KB_OS_PREPARED" not in rest and "\nlook\n" in rest


def _prep() -> str:
    return SCRIPT[SCRIPT.index("<<'PREP'") : SCRIPT.index("\nPREP\n")]


def test_preparing_reads_install_shs_own_lists_without_running_it():
    prep = _prep()
    assert "sed '/^case \"${1:-}\" in$/,$d' /root/install.sh" in prep
    assert len(re.findall(r'^case "\$\{1:-\}" in$', INSTALL, re.M)) == 1  # the one line that starts its run
    assert ". /root/install-functions.sh" in prep and "$TOOLS" in prep and "missing " in prep


def test_preparing_builds_zfs_the_way_install_sh_does():
    prep = _prep()
    for line in (
        "for pkg in zfs-dkms zfsutils-linux; do",
        "if grep -rqs 'trixie-backports' /etc/apt/sources.list /etc/apt/sources.list.d; then",
        "-t trixie-backports",
        "sed -i 's/^Components: main$/Components: main contrib non-free-firmware/'",
        "linux-headers-$(uname -r)",
    ):
        assert line in prep, line
        assert line in INSTALL, line  # the same as the installer, so a drift shows here


def test_preparing_installs_nothing_the_installer_would_refuse():
    prep = _prep()
    assert "--download-only $need" in prep  # Samba's own config would make the installer refuse
    assert "cloud-init clean" in prep and "truncate -s 0 /etc/machine-id" in prep
    tail = SCRIPT[SCRIPT.index("\nPREP\n") :]
    assert "exit 0" in tail.split('stage "Kiboto installs itself"')[0]  # it never goes on to check


@pytest.mark.skipif(not shutil.which("sh"), reason="no shell")
def test_the_script_is_still_valid_shell():
    done = subprocess.run(
        ["sh", "-n", os.path.join(ROOT, "scripts", "os_install_check.sh")], capture_output=True, text=True, check=False
    )  # noqa: S603,S607
    assert done.returncode == 0, done.stderr


def test_the_fast_path_is_asked_for_and_off_unless_asked():
    wf = _wf("os-install.yml")
    on = wf.get("on") or wf.get(True)
    for trigger in ("workflow_dispatch", "workflow_call"):
        fast = on[trigger]["inputs"]["fast"]
        assert fast["type"] == "boolean" and fast["default"] is False


def test_a_prepared_disk_belongs_to_one_installer_one_check_and_one_debian():
    steps = {s.get("name"): s for s in _wf("os-install.yml")["jobs"]["install"]["steps"]}
    key = steps["Which prepared disk fits"]["run"]
    assert "cat packaging/install.sh scripts/os_install_check.sh | sha256sum" in key
    assert "SHA512SUMS" in key and "debian-13-generic-amd64.qcow2" in key
    check = steps["Install Kiboto OS in a fresh Debian 13 and check it"]
    assert "cache-hit == 'true'" in check["env"]["KB_OS_PREPARED"]
    for name in ("Prepare a disk for the next runs", "Keep the prepared disk"):
        assert steps[name]["if"] == "inputs.fast && steps.prepared.outputs.cache-hit != 'true'"
    assert steps["Keep the prepared disk"]["with"]["key"] == "${{ steps.key.outputs.key }}"


def test_the_arm64_trial_tags_nothing_and_runs_only_by_hand():
    wf = _wf("image-build-trial.yml")
    on = wf.get("on") or wf.get(True)
    assert list(on) == ["workflow_dispatch"]
    build = wf["jobs"]["build-arch"]
    assert build["runs-on"] == "${{ matrix.runner }}"
    runners = {i["arch"]: i["runner"] for i in build["strategy"]["matrix"]["include"]}
    assert runners == {"amd64": "ubuntu-24.04", "arm64": "ubuntu-24.04-arm"}  # no emulation
    step = next(s for s in build["steps"] if s.get("id") == "build")
    assert step["with"]["platforms"] == "linux/${{ matrix.arch }}"
    assert "push-by-digest=true" in step["with"]["outputs"]
    assert step["with"]["cache-from"].startswith("type=registry,")
    join = "\n".join(str(s.get("run", "")) for s in wf["jobs"]["join"]["steps"])
    assert "imagetools create --dry-run" in join  # prints the index; nothing tagged
    assert re.search(r"manifests/\$digest", join)  # pushed by its digest only
    assert "setup-qemu" not in _read(".github", "workflows", "image-build-trial.yml")
