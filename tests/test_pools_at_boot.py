"""The boot step that brings Kiboto's pools back before Docker and the file servers start, and the
files that make Kiboto the service of a machine (packaging/)."""

import os
import re
import subprocess

from backend.hardware.pal import pool_registry
from backend.services import pools_at_boot

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, "packaging", name), encoding="utf-8") as f:
        return f.read()


def test_the_step_says_what_it_did_and_fails_when_a_pool_is_away(monkeypatch, capsys):
    monkeypatch.setattr(pool_registry, "bring_back_all", lambda run: {"media": "", "docs": "can't find UUID=e-1"})
    assert pools_at_boot.main() == 1
    out = capsys.readouterr().out
    assert "media: there" in out and "docs: NOT there: can't find UUID=e-1" in out
    monkeypatch.setattr(pool_registry, "bring_back_all", lambda run: {"media": ""})
    assert pools_at_boot.main() == 0
    monkeypatch.setattr(pool_registry, "bring_back_all", lambda run: {})
    assert pools_at_boot.main() == 0  # no pools yet is not a failure


def test_its_command_runner_answers_for_a_missing_or_stuck_tool(monkeypatch):
    assert pools_at_boot._run(["true"]) == (0, "", "")
    assert pools_at_boot._run(["no-such-tool-kb"])[0] == 127

    def stuck(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 120)

    monkeypatch.setattr(pools_at_boot.subprocess, "run", stuck)
    assert pools_at_boot._run(["mount"]) == (124, "", "Command timed out")


def test_the_pools_come_before_docker_and_the_file_servers():
    unit = _read("kiboto-pools.service")
    before = re.search(r"^Before=(.*)$", unit, re.M).group(1).split()
    assert {"docker.service", "smbd.service", "nfs-server.service"} <= set(before)
    assert "ExecStart=/opt/kiboto/current/venv/bin/python -m backend.services.pools_at_boot" in unit
    main = _read("kiboto.service")
    assert "kiboto-pools.service" in re.search(r"^After=(.*)$", main, re.M).group(1)
    for env in ("DATA_DIR=/var/lib/kiboto", "HOST_PROC=/proc", "HOST_SYS=/sys", "HOST_DEV=/dev"):
        assert f"Environment={env}" in main and f"Environment={env}" in unit
    assert "EnvironmentFile=-/etc/kiboto/kiboto.env" in main  # the person's own settings survive an update


def test_the_install_script_keeps_its_promises():
    sh = _read("install.sh")
    assert subprocess.run(["sh", "-n", os.path.join(ROOT, "packaging", "install.sh")]).returncode == 0
    # the mark that makes a machine Kiboto's (backend/runtime.py) is the one the script leaves
    with open(os.path.join(ROOT, "backend", "runtime.py"), encoding="utf-8") as f:
        assert 'MANAGED_MARK = "/etc/kiboto/managed"' in f.read()  # read from the file: tests pin the mark itself
    assert '"$ETC/managed"' in sh and "ETC=/etc/kiboto" in sh
    # it refuses a machine that already serves files or runs containers
    for said in ("Samba is already set up", "Docker already has containers", "NFS exports are already set up"):
        assert said in sh
    # kernel, ZFS and Docker are held, and given back on uninstall
    held = re.search(r'^HELD="(.*)"$', sh, re.M).group(1).split()
    assert held == ["linux-image-amd64", "linux-headers-amd64", "zfs-dkms", "zfsutils-linux", "docker.io"]
    assert "apt-mark hold $HELD" in sh and "apt-mark unhold $HELD" in sh
    # Docker gets an address range that cannot clash with a home network or an outer Docker
    assert '"bip": "10.212.0.1/24"' in sh and '"base": "10.213.0.0/16"' in sh and '"max-size": "10m"' in sh
    # pools and settings are not removed by an uninstall without --purge
    un = sh[sh.index("uninstall() {") : sh.index('case "${1:-}" in')]
    assert "zpool" not in un and "wipefs" not in un and "mkfs" not in un
    assert un.index('rm -rf "$DATA" "$ETC"') > un.index('"--purge"')


def test_a_published_version_is_installed_by_its_digest_only():
    sh = _read("install.sh")
    assert "name the version by its digest" in sh and "*@sha256:*) ;;" in sh
    assert 'must_be_a_digest "$image"; must_be_this_machine' in sh  # said before anything is installed
    took = sh[sh.index("code_from_image() {") : sh.index("service() {")]
    assert "docker create" in took and "docker run" not in took and "docker start" not in took  # nothing of it runs
    # the service files come with the version: the image carries them, and the release is where the units are read from
    with open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8") as f:
        assert "COPY packaging/ ./packaging/" in f.read()
    with open(os.path.join(ROOT, ".dockerignore"), encoding="utf-8") as f:
        assert "!packaging/" in f.read().splitlines()
    assert 'service "$PREFIX/current"' in sh


def _stamp(image):
    import subprocess

    return subprocess.run(  # noqa: S603
        ["sh", os.path.join(ROOT, "scripts", "stamp_installer.sh"), image],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_release_carries_an_install_script_that_names_its_own_image():
    image = "ghcr.io/fr0styx/kiboto@sha256:" + "ab12" * 16
    done = _stamp(image)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines.count(f'KIBOTO_IMAGE="{image}"') == 1
    # nothing else differs from the script in the repository
    assert [ln for ln in lines if not ln.startswith("KIBOTO_IMAGE=")] == [
        ln for ln in _read("install.sh").splitlines() if not ln.startswith("KIBOTO_IMAGE=")
    ]
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
        ci = f.read()
    assert "sh scripts/stamp_installer.sh" in ci and "files: install.sh" in ci


def test_an_image_named_by_a_tag_or_with_odd_characters_is_not_stamped():
    for image in (
        "ghcr.io/fr0styx/kiboto:latest",
        "",
        "x@sha256:abc",
        "a|b@sha256:" + "0" * 64,
        "a b@sha256:" + "0" * 64,
    ):
        done = _stamp(image)
        assert done.returncode == 2, image
        assert done.stdout == ""


def test_a_second_run_leaves_the_held_packages_as_they_are():
    sh = _read("install.sh")
    step = sh[sh.index("packages() {") : sh.index("docker_setup() {")]
    # every install line takes only what is missing: none names a held package outright
    installs = [ln for ln in step.splitlines() if "apt-get install" in ln]
    assert installs and all(("$need" in ln or '"$headers"' in ln) for ln in installs), installs
    assert 'headers="linux-headers-$(uname -r)"' in step  # ZFS is built for the kernel that runs
