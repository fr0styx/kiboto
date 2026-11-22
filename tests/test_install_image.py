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
    assert "ConditionPathExists=!/etc/kiboto/managed" in late and "ExecStart=/bin/sh /root/kiboto-install.sh" in late
    assert "in-target systemctl enable kiboto-firstboot.service" in late
    assert "PermitRootLogin yes" in late  # the password typed at install signs in over SSH, until SSH is off
    assert "/cdrom/kiboto/authorized_keys" in late


def test_the_build_puts_kiboto_first_and_stamps_the_release():
    build = _read("build-image.sh")
    assert "stamp_installer.sh" in build and "-boot_image any replay" in build
    assert "menuentry --hotkey=k 'Install Kiboto'" in build and "menu default" in build
    assert "preseed/file=/cdrom/kiboto/preseed.cfg" in build


@pytest.mark.skipif(not shutil.which("sh"), reason="no shell")
def test_the_scripts_are_valid_shell():
    for name in ("build-image.sh", "late.sh"):
        done = subprocess.run(["sh", "-n", os.path.join(IMAGE, name)], capture_output=True, text=True, check=False)  # noqa: S603,S607
        assert done.returncode == 0, (name, done.stderr)
