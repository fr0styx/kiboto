"""Kiboto's install image: Debian's installer that asks only for the system disk and the root password."""

import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(ROOT, "packaging", "image")


def _read(name):
    with open(os.path.join(IMAGE, name), encoding="utf-8") as f:
        return f.read()


def _answers():
    """{question: value} from the preseed file."""
    out = {}
    for line in _read("preseed.cfg").splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 3 and not line.startswith("#"):
            out[parts[1]] = parts[3] if len(parts) == 4 else ""
    return out


def test_the_two_questions_are_left_to_the_person():
    said = _answers()
    # which disk becomes the system disk, and whether to write to it: asked every time
    assert "partman-auto/disk" not in said and "partman/confirm" not in said
    assert "partman/confirm_nooverwrite" not in said  # the confirmation for an empty disk is asked too
    assert said["partman-auto/init_automatically_partition"] == "some_device"  # the whole disk, no method question
    # the root password: typed during the install, never on the image
    assert "passwd/root-password" not in said and "passwd/root-password-crypted" not in said
    assert said["passwd/root-login"] == "true" and said["passwd/make-user"] == "false"


def test_everything_else_is_answered():
    said = _answers()
    for question in (
        "debian-installer/locale",
        "keyboard-configuration/xkb-keymap",
        "netcfg/get_hostname",
        "mirror/http/hostname",
        "apt-setup/contrib",
        "apt-setup/cdrom/set-first",
        "partman-auto/method",
        "tasksel/first",
        "grub-installer/bootdev",
        "preseed/late_command",
    ):
        assert question in said, question
    assert said["preseed/late_command"] == "sh /cdrom/kiboto/late.sh"
    assert "ssh-server" in said["tasksel/first"]


def test_kiboto_is_installed_once_at_the_first_start():
    late = _read("late.sh")
    assert "cp /cdrom/kiboto/install.sh /target/root/kiboto-install.sh" in late
    assert "ConditionPathExists=!/etc/kiboto/managed" in late and "ExecStart=/bin/sh /root/kiboto-firstboot.sh" in late
    assert "in-target systemctl enable kiboto-firstboot.service" in late
    assert "PermitRootLogin yes" in late  # the password typed at install signs in over SSH, until SSH is off
    assert "/cdrom/kiboto/authorized_keys" in late


def test_the_build_puts_kiboto_first_and_stamps_the_release():
    build = _read("build-image.sh")
    assert "stamp_installer.sh" in build and "-boot_image any replay" in build
    assert "menuentry --hotkey=k 'Install Kiboto'" in build and "menu default" in build
    assert "preseed/file=/cdrom/kiboto/preseed.cfg" in build


def test_the_image_says_what_it_is_made_of_and_where_debians_sources_are():
    build = _read("build-image.sh")
    assert '-map "$work/NOTICE.txt" /kiboto/NOTICE.txt' in build
    notice = _read("NOTICE.txt")
    assert "@DEBIAN_IMAGE@" in notice and "MIT licence" in notice
    assert "https://cdimage.debian.org/cdimage/release/@DEBIAN_VERSION@/source/" in notice
    assert "snapshot.debian.org" in notice and "/third-party-licences.txt" in notice
    # the written offer: three years, at cost, asked for in the open, naming the release
    assert "for three years after a Kiboto release" in notice and "no more than the cost" in notice
    assert "https://github.com/fr0styx/kiboto/issues" in notice and "Source request" in notice
    with open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8") as f:
        docker = f.read()
    assert "third_party.py /tmp/licences/package-lock.json > /app/static/third-party-licences.txt" in docker


@pytest.mark.skipif(not shutil.which("sh"), reason="no shell")
def test_the_scripts_are_valid_shell():
    for name in ("build-image.sh", "late.sh"):
        done = subprocess.run(["sh", "-n", os.path.join(IMAGE, name)], capture_output=True, text=True, check=False)  # noqa: S603,S607
        assert done.returncode == 0, (name, done.stderr)


def test_a_release_builds_the_install_image_from_checked_debian_files():
    with open(os.path.join(ROOT, "scripts", "build_release_image.sh"), encoding="utf-8") as f:
        build = f.read()
    assert "DEBIAN_CD_KEY=DF9B9C49EAA9298432589D76DA87E80D6294BE9B" in build  # pinned public fingerprint gitleaks:allow
    assert "VALIDSIG $DEBIAN_CD_KEY" in build and "sha256sum -c" in build
    assert build.index("sha256sum -c") < build.index("build-image.sh")  # nothing is built from an unchecked file
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
        ci = f.read()
    step = ci[ci.index("- name: Build the install image") : ci.index("- name: Create Release")]
    assert "continue-on-error: true" in step and "scripts/build_release_image.sh" in step
    assert "gh release upload" in ci


def test_the_first_start_says_on_the_screen_what_happens():
    late = _read("late.sh")
    run = late[late.index("<<'RUN'") : late.index("\nRUN\n")]
    assert "sh /root/kiboto-install.sh" in run and 'exit "$rc"' in run  # a failure fails the service: it tries again
    assert "Kiboto is installing itself" in run and "Kiboto could not install itself" in run
    assert "restart the machine to try again" in run and "agetty --reload" in run
    assert (
        'install -m 600 /dev/null "$LOG"' in run and "umask" not in run
    )  # the log holds the code; install.sh keeps its own umask
    assert "KIBOTO_ACCEPT_MAIN_BUILDS" in run and ". /etc/kiboto/kiboto.env" not in run  # read, never run


def test_the_ssh_generator_does_not_bury_the_code():
    late = _read("late.sh")
    assert "ln -sf /dev/null /target/etc/systemd/system-generators/systemd-ssh-generator" in late
