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
    assert "ConditionPathExists=|!/etc/kiboto/managed" in late and "ExecStart=/bin/sh /root/kiboto-firstboot.sh" in late
    assert "in-target systemctl enable kiboto-firstboot.service" in late
    assert "PermitRootLogin yes" in late  # the password typed at install signs in over SSH, until SSH is off
    assert "/cdrom/kiboto/authorized_keys" in late


def test_a_first_start_that_stopped_late_runs_again_at_the_next_start():
    """install.sh marks the machine as Kiboto's before it waits for Kiboto and moves the network. A
    stop after that used to leave the first-start service skipped for good; the started mark,
    which install.sh removes as its last step, now starts it again."""
    late = _read("late.sh")
    unit = late[late.index("[Unit]\nDescription=Install Kiboto") : late.index("[Service]")]
    conditions = [line for line in unit.splitlines() if line.startswith("Condition")]
    assert conditions == [
        "ConditionPathExists=|!/etc/kiboto/managed",  # "|": either one is enough
        "ConditionPathExists=|/etc/kiboto/install-started",
    ]
    with open(os.path.join(ROOT, "packaging", "install.sh"), encoding="utf-8") as f:
        install = f.read()
    assert "ETC=/etc/kiboto\n" in install
    assert 'mark_started() { mkdir -p "$ETC"; : > "$ETC/install-started"; }' in install
    service = install[install.index("\nservice() {") : install.index("\nwait_up() {")]
    assert '> "$ETC/managed"' in service  # the mark that used to end the retries is written this early
    for branch in ("--from)", '--image | "")'):
        part = install[install.index(branch) :]
        part = part[: part.index(";;")]
        assert part.index("service ") < part.index("wait_up") < part.index('rm -f "$ETC/install-started"')


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


def test_a_release_without_its_install_image_is_red():
    """v2.0.6 went out green with no install image: the two steps that make and attach it may fail
    without failing the job. The last step asks the release itself, and has no way to pass quietly."""
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
        ci = f.read()
    attach = ci[
        ci.index("- name: Attach the install image") : ci.index("- name: The release carries the install image")
    ]
    assert "--clobber" in attach  # a second run replaces what a first one left
    check = ci[ci.index("- name: The release carries the install image") :]
    assert "continue-on-error" not in check and "\n        if:" not in check
    assert "gh release view" in check and ".assets[].name" in check
    assert 'grep -qxF "$iso"' in check and "exit 1" in check
    assert check.index("exit 0") < check.index("::error title=No install image::") < check.index("exit 1")


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


def test_a_finished_first_start_draws_the_code_again_below_its_last_lines():
    late = _read("late.sh")
    run = late[late.index("<<'RUN'") : late.index("\nRUN\n")]
    tail = run[run.index('if [ "$rc" != 0 ]; then') :]
    ok = tail[tail.index("\nelse\n") : tail.index("\nfi\n")]
    assert "agetty --reload" in ok


def _installer():
    with open(os.path.join(ROOT, "packaging", "install.sh"), encoding="utf-8") as f:
        return f.read()


def _install_functions(tmp_path, arch="amd64", cosign_body="#!/bin/sh\nexit 0\n", verify_rc=0):
    """install.sh's functions with dpkg, curl and the downloaded cosign replaced by stand-ins."""
    sh = _installer()
    funcs = tmp_path / "f.sh"
    funcs.write_text(sh[: sh.index('case "${1:-}" in\n')])
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "dpkg").write_text(f"#!/bin/sh\necho {arch}\n")
    body = tmp_path / "body"
    body.write_text(cosign_body.replace("RC", str(verify_rc)))
    # curl writes the stand-in cosign where -o says, and notes what it was asked for
    (bin_ / "curl").write_text(
        f'#!/bin/sh\nwhile [ $# -gt 0 ]; do case $1 in -o) out=$2; shift;; https*) echo "$1" >> {tmp_path}/asked;; esac; shift; done\n'
        f'cp {body} "$out"\n'
    )
    for f in ("dpkg", "curl"):
        os.chmod(bin_ / f, 0o755)
    return funcs, bin_


def _run(tmp_path, funcs, bin_, script):
    env = {"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(tmp_path)}
    return subprocess.run(["sh", "-c", f". {funcs}; {script}"], env=env, capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="needs sha256sum")
def test_an_image_the_script_does_not_name_needs_the_pinned_cosign(tmp_path):
    funcs, bin_ = _install_functions(tmp_path)
    r = _run(tmp_path, funcs, bin_, "must_be_signed_before_unpacking ghcr.io/x/y@sha256:" + "a" * 64)
    # the stand-in is not the cosign the script names: nothing of the image is looked at
    assert r.returncode != 0 and "is not the one this script names" in r.stderr + r.stdout
    asked = (tmp_path / "asked").read_text()
    assert asked.strip() == "https://github.com/sigstore/cosign/releases/download/v3.1.4/cosign-linux-amd64"


def test_the_named_image_and_an_unsigned_build_skip_it(tmp_path):
    funcs, bin_ = _install_functions(tmp_path)
    image = "ghcr.io/x/y@sha256:" + "b" * 64
    r = _run(tmp_path, funcs, bin_, f"KIBOTO_IMAGE={image}; must_be_signed_before_unpacking {image}; echo went-on")
    assert r.returncode == 0 and "went-on" in r.stdout and not (tmp_path / "asked").exists()
    r = _run(tmp_path, funcs, bin_, f"must_be_signed_before_unpacking {image} --unsigned; echo went-on")
    assert r.returncode == 0 and "went-on" in r.stdout and not (tmp_path / "asked").exists()


def test_a_processor_without_a_pinned_cosign_is_refused(tmp_path):
    funcs, bin_ = _install_functions(tmp_path, arch="riscv64")
    r = _run(tmp_path, funcs, bin_, "must_be_signed_before_unpacking ghcr.io/x/y@sha256:" + "c" * 64)
    assert r.returncode != 0 and "--unsigned" in r.stderr + r.stdout and not (tmp_path / "asked").exists()


def test_the_check_comes_before_anything_is_unpacked():
    sh = _installer()
    order = sh[sh.index('--image | "")') :]
    assert order.index("must_be_signed_before_unpacking") < order.index('code_from_image "$image"')
    step = sh[sh.index("must_be_signed_before_unpacking() {") : sh.index("must_be_signed() {")]
    # a release only, unless main builds are asked for; the signer is this project's CI
    assert "tags/v[0-9][^/]*$" in step and "KIBOTO_ACCEPT_MAIN_BUILDS:-0" in step
    assert "--certificate-oidc-issuer https://token.actions.githubusercontent.com" in step
    assert len(set(sh.split("COSIGN_SHA256_AMD64=")[1][:64])) > 4  # a real checksum, written in
