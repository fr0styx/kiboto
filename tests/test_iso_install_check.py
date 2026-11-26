"""The install image (the USB image) is installed for real in a virtual machine before Stable."""

import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "iso_install_check.sh")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_the_script_is_valid_shell_and_needs_a_digest():
    assert subprocess.run(["sh", "-n", SCRIPT]).returncode == 0
    done = subprocess.run(["sh", SCRIPT, "ghcr.io/fr0styx/kiboto:latest"], capture_output=True, text=True)
    assert done.returncode == 2 and "usage" in done.stderr


def test_the_image_is_built_as_a_release_builds_it_with_this_runs_answers_only():
    sh = _read("scripts", "iso_install_check.sh")
    assert "scripts/build_release_image.sh" in sh  # Debian's netinst, checked against Debian's key
    answers = sh[sh.index("<<ANSWERS") : sh.index("\nANSWERS\n")]
    assert "partman-auto/disk string /dev/vda" in answers and "partman/confirm boolean true" in answers
    assert "passwd/root-password-crypted password $crypted" in answers  # random and hashed, never shown
    assert "root-password password" not in answers and "root-password-again" not in answers
    assert "openssl passwd -6 -stdin" in sh
    assert "KIBOTO_ACCEPT_MAIN_BUILDS=1" in sh[sh.index('if [ "${KB_ISO_MAIN:-0}" = 1 ]') :]
    # the release itself gets none of it
    release = _read("scripts", "build_release_image.sh")
    assert '"${KIBOTO_EXTRA_PRESEED:-}"' in release
    build = _read("packaging", "image", "build-image.sh")
    assert "${KIBOTO_EXTRA_ARGS:+ $KIBOTO_EXTRA_ARGS}" in build
    # BIOS: Debian's graphical entry no longer starts by itself instead of Kiboto's
    assert "sed -e '/^default /d' -e '/menu default/d' \"$work/gtk.cfg\"" in build
    assert '-map "$work/gtk.new" /isolinux/gtk.cfg' in build
    # and Debian's speech installer no longer starts by itself after its own 30 seconds
    assert "-e '/^ontimeout /d'" in build and '-map "$work/spkgtk.new" /isolinux/spkgtk.cfg' in build


def test_it_checks_what_an_install_from_the_image_promises():
    sh = _read("scripts", "iso_install_check.sh")
    for promise in (
        "from-install-image",
        "nft list table inet kiboto",
        "sshd_config.d/kiboto.conf",
        "52kiboto-security",
        "first-run",
    ):
        assert promise in sh, promise


def test_stable_waits_for_an_install_from_the_releases_image():
    import yaml

    wf = yaml.safe_load(_read(".github", "workflows", "promote.yml"))
    names = [s.get("name", "") for s in wf["jobs"]["promote"]["steps"]]
    iso = names.index("Install Kiboto OS from the release's install image")
    assert iso < names.index("Verify and retag the soaked images") < names.index("Mark the release as the latest")
    step = wf["jobs"]["promote"]["steps"][iso]
    assert 'KB_ISO_FROM="$GITHUB_WORKSPACE/release"' in step["run"] and "iso_install_check.sh" in step["run"]
    release = next(s for s in wf["jobs"]["promote"]["steps"] if s.get("name") == "Checkout the release")
    assert release["with"]["ref"] == "${{ steps.pick.outputs.tag }}" and release["with"]["path"] == "release"
