"""The test setup keeps every test away from the machine it runs on (conftest._never_the_real_machine)."""

import os
import subprocess
import sys

import pytest

from backend import door
from backend.services import host_power
from tests.machine_guard import powers_off


def test_no_test_sees_a_host_door():
    assert not os.path.exists(door.SOCK)
    assert not door.available()
    with pytest.raises(OSError):
        door.call("door.ping", timeout=1)


@pytest.mark.parametrize(
    "argv",
    [
        ["/usr/sbin/poweroff"],
        ["reboot"],
        "shutdown -h now",
        ["systemctl", "poweroff"],
        ["systemctl", "--no-wall", "reboot"],
        ["/host/powerdown"],
    ],
)
def test_power_commands_are_caught(argv):
    assert powers_off(argv)


@pytest.mark.parametrize("argv", [["systemctl", "status", "kiboto"], ["ls", "-l"], "echo reboot", []])
def test_other_commands_are_not(argv):
    assert not powers_off(argv)


def test_a_fake_in_the_temporary_folder_still_runs(tmp_path):
    fake = tmp_path / "poweroff"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    assert not powers_off([str(fake)])


def test_running_a_power_command_fails_the_test():
    with pytest.raises(AssertionError, match="switch off or restart"):
        subprocess.run(["poweroff"], capture_output=True)


def test_host_power_out_of_test_mode_cannot_reach_the_machine(monkeypatch):
    """tests/test_host_power.py leaves test mode on purpose; on a test machine with a door, its
    shutdown once went to the real door, which powered the machine off."""
    monkeypatch.setattr(host_power, "test_mode", lambda: False)
    monkeypatch.setattr(host_power, "commands", lambda action: ["/usr/sbin/poweroff"])  # as on a real host
    with pytest.raises(AssertionError, match="switch off or restart"):
        host_power.run("shutdown")


def test_ordinary_commands_still_run():
    assert subprocess.run([sys.executable, "-c", "print(1)"], capture_output=True, text=True).stdout.strip() == "1"
