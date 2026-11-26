"""The Kiboto OS install check: a real install in a virtual machine (scripts/os_install_check.sh),
run by its own workflow. These tests keep the script and the workflow from being weakened quietly;
what the script itself does can only be seen by running it (it was tried on a machine with KVM
against a good build and against a deliberately broken installer, which it reported and failed)."""

import os
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "os_install_check.sh")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "os-install.yml")


def _script() -> str:
    with open(SCRIPT, encoding="utf-8") as f:
        return f.read()


def _workflow() -> dict:
    with open(WORKFLOW, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.mark.skipif(not shutil.which("sh"), reason="no shell")
def test_the_script_is_valid_shell_and_names_its_use():
    done = subprocess.run(["sh", "-n", SCRIPT], capture_output=True, text=True, check=False)  # noqa: S603,S607
    assert done.returncode == 0, done.stderr
    asked = subprocess.run(["sh", SCRIPT], capture_output=True, text=True, check=False)  # noqa: S603,S607
    assert asked.returncode == 2 and "usage:" in asked.stderr
    tagged = subprocess.run(
        ["sh", SCRIPT, "ghcr.io/fr0styx/kiboto:latest"], capture_output=True, text=True, check=False
    )  # noqa: S603,S607
    assert tagged.returncode == 2  # a tag can move: only a digest names one build


def test_it_installs_this_checkouts_script_from_a_checked_debian():
    text = _script()
    assert '"${KB_OS_INSTALLER:-$HERE/packaging/install.sh}"' in text
    assert "sh /root/install.sh --image '$IMAGE' --unsigned" in text  # before a build is signed
    assert "cloud.debian.org/images/cloud/trixie/latest" in text and "SHA512SUMS" in text
    check = text.index('= "$want" ] || { say "the Debian image does not match')
    assert check < text.index("docker run -d --name")  # nothing starts from an unchecked image
    assert "-enable-kvm" in text and "[ -e /dev/kvm ]" in text


def test_every_check_runs_before_and_after_a_restart_and_a_failed_one_fails_the_run():
    text = _script()
    look = text[text.index("look() {") : text.index("\n}\n", text.index("look() {"))]
    checks = re.findall(r'^  check "([^"]+)"', look, re.M)
    assert len(checks) >= 14
    for wanted in (
        "Kiboto's service is running",
        "Kiboto's root service is running",
        "the web process runs as its own user, not as root",
        "no service of the machine has failed",
        "ZFS is loaded and its tools answer",
        "Docker runs",
    ):
        assert wanted in checks, wanted
    # one name for each is-active: with two names systemd is satisfied by either
    assert not re.search(r"is-active -q \S+ \S+\"", look)
    after = text[text.index('stage "The installed machine"') :]
    assert after.count("\nlook\n") == 2 and "systemctl reboot" in after
    assert after.index("\nlook\n") < after.index("systemctl reboot") < after.rindex("\nlook\n")
    end = text[text.index('stage "Result"') :]
    assert 'if [ "$failed" != 0 ]; then' in end and "exit 1" in end
    assert "failed=$((failed + 1))" in text


@pytest.mark.skipif(not shutil.which("sh"), reason="no shell")
def test_a_first_sign_in_code_is_never_shown():
    text = _script()
    hide = re.search(r"^hide\(\) \{.*\}$", text, re.M).group(0)
    shown = subprocess.run(  # noqa: S603,S607
        ["sh", "-c", hide + "\nprintf 'the code:\\n    AB12-CD34-EF56\\nKiboto 2.0.6\\n' | hide"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "AB12" not in shown and "(code not shown)" in shown and "Kiboto 2.0.6" in shown
    # everything read from the machine after the install goes through it
    for line in text.splitlines():
        if "install.log" in line and "tail" in line:
            assert "| hide" in line, line


def test_the_workflow_runs_it_for_one_of_kibotos_own_builds_only():
    wf = _workflow()
    on = wf.get("on") or wf.get(True)  # YAML reads a bare `on` as true
    assert "workflow_dispatch" in on and "workflow_call" in on
    job = wf["jobs"]["install"]
    assert job["runs-on"] == "ubuntu-latest" and "continue-on-error" not in str(job)
    assert job["permissions"] == {"contents": "read", "packages": "read", "actions": "read"}
    steps = job["steps"]
    runs = "\n".join(str(s.get("run", "")) for s in steps)
    assert r"^ghcr\.io/fr0styx/kiboto@sha256:[0-9a-f]{64}$" in runs
    assert 'sh scripts/os_install_check.sh "$IMAGE_REF"' in runs
    # what a person types is never put into a command line: it arrives as a value
    assert "${{ inputs.image }}" not in runs
    for step in steps:
        if "uses" in step:
            assert re.search(r"@[0-9a-f]{40}$", step["uses"]), step["uses"]  # pinned by commit


def test_no_build_is_signed_or_tagged_unless_kiboto_os_installs_from_it():
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
        jobs = yaml.safe_load(f)["jobs"]
    job = jobs["os-install"]
    assert job["uses"] == "./.github/workflows/os-install.yml"
    # it starts with the run (early) and so runs exactly when the image is built
    assert "needs" not in job and job["if"] == jobs["build-image"]["if"]
    assert job["with"]["early"] is True and "continue-on-error" not in str(job)
    assert "image" not in job.get("with", {})  # no build named: it installs the one this run built
    assert job["permissions"] == {"contents": "read", "packages": "read", "actions": "read"}
    assert "os-install" in jobs["publish"]["needs"]
    # and the workflow takes that build from the run when it is given none
    steps = _workflow()["jobs"]["install"]["steps"]
    fetch = next(s for s in steps if s.get("name") == "Download the digest")
    assert fetch["if"] == "inputs.image == '' && !inputs.early" and fetch["with"]["name"] == "digest-full"


def test_early_waits_for_this_runs_full_build_and_boots_with_the_last_main_build():
    steps = _workflow()["jobs"]["install"]["steps"]
    for name in ("Install Kiboto OS in a fresh Debian 13 and check it", "Prepare a disk for the next runs"):
        env = next(s for s in steps if s.get("name") == name)["env"]
        # QEMU from :main only while waiting; a build given by digest boots with its own
        assert (
            env["KB_OS_VM_IMAGE"]
            == "${{ steps.build.outputs.image == '--wait' && 'ghcr.io/fr0styx/kiboto:main' || '' }}"
        )
        assert env["KB_OS_IMAGE_CMD"] == 'sh scripts/ci_wait_build.sh digest-full "Build multi-arch image (full)"'
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
        ci = yaml.safe_load(f)["jobs"]["build-image"]
    assert ci["name"] == "Build multi-arch image (${{ matrix.variant }})"  # the job the check waits for


def test_the_waiter_installs_only_a_digest_and_stops_when_the_build_fails():
    with open(os.path.join(ROOT, "scripts", "ci_wait_build.sh"), encoding="utf-8") as f:
        src = f.read()
    assert "^sha256:[0-9a-f]{64}$" in src
    assert "completed*) echo" in src and "exit 1" in src  # failed, cancelled or skipped: no long wait
    assert "KB_WAIT_MINUTES:-40" in src


def test_wait_needs_a_command_and_a_vm_image(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("KB_OS_")}
    r = subprocess.run(
        ["sh", os.path.join(ROOT, "scripts", "os_install_check.sh"), "--wait"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 2 and "KB_OS_IMAGE_CMD" in r.stderr


def test_a_tag_also_tries_an_update_and_revert_through_the_root_service():
    with open(SCRIPT, encoding="utf-8") as f:
        sh = f.read()
    step = sh[sh.index('if [ "${KB_OS_UPDATE:-0}" = 1 ]; then') : sh.index('stage "Result"')]
    assert 'door.call("update.start"' in step and 'door.call("update.back"' in step
    assert step.index("update.start") < step.index("update.back")
    assert step.count("look") == 2  # the whole check after each switch
    assert "KIBOTO_ACCEPT_MAIN_BUILDS=1" in step and "UPDATE_SIGNATURES=off" in step  # a test machine only
    with open(WORKFLOW, encoding="utf-8") as f:
        wf = f.read()
    assert "KB_OS_UPDATE: ${{ inputs.fast && '0' || '1' }}" in wf


def test_a_fresh_install_takes_its_python_packages_from_the_image():
    with open(os.path.join(ROOT, "scripts", "os_install_check.sh"), encoding="utf-8") as f:
        check = f.read()
    with open(os.path.join(ROOT, "packaging", "install.sh"), encoding="utf-8") as f:
        install = f.read()
    assert "Python packages: taken from the image" in install
    assert "grep -q 'Python packages: taken from the image' /root/install.log" in check
