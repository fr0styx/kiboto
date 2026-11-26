"""Debian's security fixes on Kiboto OS: by themselves, the kernel included, never a restart."""

import dataclasses
import os
import shutil
import subprocess

import pytest

from backend import config
from backend.services import security_updates as sec

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "packaging", "kiboto-kernel-zfs.sh")


class Calls:
    def __init__(self, held=""):
        self.seen, self.held = [], held

    def __call__(self, cmd, timeout=300):
        self.seen.append(cmd)
        if cmd == ["apt-mark", "showhold"]:
            return 0, self.held
        return 0, ""


@pytest.fixture
def machine(tmp_path):
    for d in ("etc/apt/apt.conf.d", "etc/default", "etc/kernel/postinst.d"):
        (tmp_path / d).mkdir(parents=True)
    return str(tmp_path)


def _setting(monkeypatch, on):
    monkeypatch.setattr(config, "SETTINGS", dataclasses.replace(config.SETTINGS, security_updates=on))


def test_the_release_files_say_what_they_promise():
    with open(os.path.join(ROOT, "packaging", "kiboto-security.apt.conf"), encoding="utf-8") as f:
        apt = f.read()
    assert 'APT::Periodic::Unattended-Upgrade "1";' in apt
    assert 'Unattended-Upgrade::Automatic-Reboot "false";' in apt  # never a restart by itself
    assert "codename=${distro_codename}-security,label=Debian-Security" in apt
    # Debian's own list (50unattended-upgrades) also takes point releases: cleared before ours
    assert apt.index("#clear Unattended-Upgrade::Origins-Pattern;") < apt.index("Origins-Pattern {")
    with open(os.path.join(ROOT, "packaging", "kiboto-grub.cfg"), encoding="utf-8") as f:
        assert "GRUB_DEFAULT=saved" in f.read()
    with open(os.path.join(ROOT, "packaging", "install.sh"), encoding="utf-8") as f:
        sh = f.read()
    assert "unattended-upgrades" in sh.split("TOOLS=")[1].split('"')[1]


def test_it_is_put_in_place_and_the_kernel_follows_debian(machine, monkeypatch):
    _setting(monkeypatch, True)
    calls = Calls(held="docker.io\nlinux-headers-amd64\nlinux-image-amd64\nzfs-dkms\n")
    changed = sec.keep_current(ROOT, calls, root=machine)
    assert sec.APT_CONF in changed and sec.GRUB_CONF in changed and "kernel follows Debian" in changed
    for hook in sec.HOOKS:  # also where the headers' own hook runs it
        assert os.stat(machine + hook).st_mode & 0o777 == 0o755
    assert ["update-grub"] in calls.seen
    assert ["apt-mark", "unhold", "linux-image-amd64", "linux-headers-amd64"] in calls.seen
    with open(machine + sec.APT_CONF, encoding="utf-8") as f:
        assert 'Unattended-Upgrade "1"' in f.read()
    # the next start finds everything as it should be: nothing is written or run again
    again = Calls(held="docker.io\nzfs-dkms\n")
    assert sec.keep_current(ROOT, again, root=machine) == [] and again.seen == [["apt-mark", "showhold"]]


def test_off_holds_the_kernel_and_stops_the_automatic_fixes(machine, monkeypatch):
    _setting(monkeypatch, False)
    calls = Calls(held="docker.io\nzfs-dkms\n")
    changed = sec.keep_current(ROOT, calls, root=machine)
    assert "kernel held" in changed and ["apt-mark", "hold", "linux-image-amd64", "linux-headers-amd64"] in calls.seen
    with open(machine + sec.APT_CONF, encoding="utf-8") as f:
        assert f.read() == sec.OFF_TEXT
    assert os.path.exists(machine + sec.HOOKS[0])  # it still guards a kernel installed by hand
    assert sec.status(root=machine)["on"] is False


def test_nothing_happens_without_apt_or_with_an_older_release(tmp_path, machine):
    calls = Calls()
    assert sec.keep_current(ROOT, calls, root=str(tmp_path / "nowhere")) == []
    assert sec.keep_current(str(tmp_path / "old-release"), calls, root=machine) == []
    assert calls.seen == []


def test_a_failed_update_grub_is_only_logged(machine, monkeypatch, caplog):
    _setting(monkeypatch, True)
    assert sec.GRUB_CONF in sec.keep_current(ROOT, lambda cmd, timeout=300: (1, "no grub"), root=machine)
    assert "update-grub failed" in caplog.text


def test_the_page_hears_when_debian_last_looked_and_which_kernel_waits(machine):
    assert sec.status(root=machine)["last"] is None and sec.status(root=machine)["kernel_without_zfs"] == ""
    stamp = machine + sec.STAMP
    os.makedirs(os.path.dirname(stamp))
    open(stamp, "w").close()
    flag = machine + sec.FLAG
    os.makedirs(os.path.dirname(flag))
    with open(flag, "w") as f:
        f.write("6.12.120+deb13-amd64\n")
    st = sec.status(root=machine)
    assert st["last"] and st["kernel_without_zfs"] == "6.12.120+deb13-amd64"


def test_commands_answer_with_their_exit_code():
    assert sec._run(["sh", "-c", "echo hi; exit 3"]) == (3, "hi\n")
    assert sec._run(["/no/such/command"])[0] == 1


# --- the kernel hook, run as Debian runs it, with stand-ins for dpkg, uname and GRUB


def _hook(tmp_path, kernels, zfs_for, running, zfs_installed=True):
    modules = tmp_path / "modules"
    for k in kernels:
        (modules / k / "kernel").mkdir(parents=True, exist_ok=True)
        if k in zfs_for:
            (modules / k / "updates" / "dkms").mkdir(parents=True, exist_ok=True)
            (modules / k / "updates" / "dkms" / "zfs.ko.xz").write_text("")
    grub = tmp_path / "grub.cfg"
    uuid = "af01cf6d-3c1a-46f8-9d6f-70e2338496fd"
    grub.write_text(
        f"submenu 'Advanced options' $menuentry_id_option 'gnulinux-advanced-{uuid}' {{\n"
        + "".join(f"  menuentry 'x' $menuentry_id_option 'gnulinux-{k}-advanced-{uuid}' {{\n" for k in kernels)
    )
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    status = "install ok installed" if zfs_installed else "unknown ok not-installed"
    stand_ins = {
        "dpkg-query": f"#!/bin/sh\nprintf '{status}'\n",
        "uname": f"#!/bin/sh\necho {running}\n",
        "grub-set-default": f'#!/bin/sh\necho "$1" >> {tmp_path}/grub-default\n',
    }
    for name, body in stand_ins.items():
        (bin_ / name).write_text(body)
        os.chmod(bin_ / name, 0o755)
    env = {
        "PATH": f"{bin_}:/usr/bin:/bin",
        "KIBOTO_MODULES": str(modules),
        "KIBOTO_GRUB_CFG": str(grub),
        "KIBOTO_ZFS_FLAG": str(tmp_path / "flag"),
    }
    done = subprocess.run(["sh", HOOK, kernels[-1]], env=env, capture_output=True, text=True)
    default = tmp_path / "grub-default"
    return done, (tmp_path / "flag"), (default.read_text().split() if default.exists() else []), uuid


needs_sort_v = pytest.mark.skipif(shutil.which("sort") is None, reason="needs sort -V")


@needs_sort_v
def test_a_new_kernel_without_zfs_keeps_the_running_one(tmp_path):
    old, new = "6.12.118+deb13-amd64", "6.12.120+deb13-amd64"
    done, flag, default, uuid = _hook(tmp_path, [old, new], zfs_for=[old], running=old)
    assert done.returncode == 0  # a kernel install never fails because of the hook
    assert flag.read_text().strip() == new
    assert default == [f"gnulinux-advanced-{uuid}>gnulinux-{old}-advanced-{uuid}"]
    assert "keeps starting" in done.stderr


@needs_sort_v
def test_once_zfs_is_built_the_newest_kernel_starts_again(tmp_path):
    old, new = "6.12.118+deb13-amd64", "6.12.120+deb13-amd64"
    (tmp_path / "flag").write_text(new + "\n")
    done, flag, default, _ = _hook(tmp_path, [old, new], zfs_for=[old, new], running=old)
    assert done.returncode == 0 and not flag.exists() and default == ["0"]


@needs_sort_v
def test_nothing_is_kept_when_there_is_nothing_to_gain(tmp_path):
    k = "6.12.120+deb13-amd64"
    # the newest is the one that runs
    (tmp_path / "a").mkdir()
    done, flag, default, _ = _hook(tmp_path / "a", [k], zfs_for=[], running=k)
    assert done.returncode == 0 and not flag.exists() and default == []
    # the running one has no ZFS either
    old = "6.12.118+deb13-amd64"
    (tmp_path / "b").mkdir()
    done, flag, default, _ = _hook(tmp_path / "b", [old, k], zfs_for=[], running=old)
    assert done.returncode == 0 and not flag.exists() and default == []
    # a machine without ZFS
    (tmp_path / "c").mkdir()
    done, flag, default, _ = _hook(tmp_path / "c", [old, k], zfs_for=[old], running=old, zfs_installed=False)
    assert done.returncode == 0 and not flag.exists() and default == []
