"""SET-31, Power stage 4: one checked way to restart or switch off the host (Power finding A11)."""

import os
import subprocess

import pytest

from backend.services import host_power as hp


@pytest.fixture
def host(tmp_path, monkeypatch):
    """No test mode, and the command lists point at files the test makes."""
    monkeypatch.setattr(hp, "test_mode", lambda: False)
    monkeypatch.setattr(
        hp, "HOST_COMMANDS", {"reboot": (str(tmp_path / "reboot"),), "shutdown": (str(tmp_path / "powerdown"),)}
    )
    monkeypatch.setattr(hp, "CONTAINER_MARK", str(tmp_path / ".dockerenv"))
    monkeypatch.setattr(hp.shutil, "which", lambda name: None)
    (tmp_path / ".dockerenv").write_text("")
    return tmp_path


def _script(path, body):
    path.write_text("#!/bin/sh\n" + body + "\n")
    os.chmod(path, 0o755)


def test_in_a_container_without_a_host_command_nothing_can_and_says_why(host):
    assert hp.commands("reboot") == []
    c = hp.can("shutdown")
    assert c["ok"] is False and "/host/powerdown" in c["why"]
    r = hp.run("reboot")
    assert r["started"] is False and "/host/reboot" in r["error"]


def test_the_host_command_runs_and_its_answer_is_read(host):
    _script(host / "powerdown", "exit 0")
    assert hp.can("shutdown") == {"ok": True, "how": str(host / "powerdown"), "why": ""}
    assert hp.run("shutdown") == {"started": True, "how": str(host / "powerdown"), "error": ""}
    _script(host / "powerdown", "exit 3")
    r = hp.run("shutdown")
    assert r["started"] is False and "exit 3" in r["error"]


def test_a_command_still_running_is_the_host_going_down(host, monkeypatch):
    _script(host / "reboot", "exit 0")

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], hp.WAIT_SECS)

    monkeypatch.setattr(hp.subprocess, "run", slow)
    assert hp.run("reboot")["started"] is True


def test_a_command_that_cannot_run_is_said(host, monkeypatch):
    _script(host / "reboot", "exit 0")

    def broken(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(hp.subprocess, "run", broken)
    r = hp.run("reboot")
    assert r["started"] is False and "could not be run" in r["error"]


def test_on_the_host_itself_the_system_command_counts(host, monkeypatch):
    os.remove(host / ".dockerenv")
    monkeypatch.setattr(hp.shutil, "which", lambda name: f"/sbin/{name}")
    assert hp.commands("shutdown") == ["/sbin/poweroff"]
    assert hp.can("reboot")["ok"] is True
    (host / "x").write_text("")
    monkeypatch.setattr(hp.shutil, "which", lambda name: None)
    assert hp.can("reboot")["why"] == "No restart or shut-down command was found on this system."


def test_test_mode_never_switches_anything_and_bad_actions_are_refused(monkeypatch):
    monkeypatch.setattr(hp, "test_mode", lambda: True)
    assert hp.run("shutdown")["how"] == "test"
    assert hp.can("reboot") == {"ok": True, "how": "test", "why": ""}
    with pytest.raises(ValueError):
        hp.commands("hibernate")


def test_the_ups_shutdown_uses_the_same_list(host):
    from backend.services import ups_watchdog

    _script(host / "powerdown", "exit 0")
    assert ups_watchdog.host_shutdown_paths() == [str(host / "powerdown")]
    assert ups_watchdog.signal_host_powerdown() is True


def test_routes_refuse_before_anything_is_stopped(client, auth_headers, monkeypatch):
    stopped = []
    monkeypatch.setattr("backend.api.system.machines_first", lambda come_back=True: stopped.append(come_back))
    monkeypatch.setattr(hp, "can", lambda action: {"ok": False, "how": "", "why": "No host command is mounted."})
    r = client.post("/api/system/reboot", headers=auth_headers)
    assert r.status_code == 409 and "No host command" in r.text and stopped == []
    assert client.get("/api/system/power-actions", headers=auth_headers).json()["shutdown"]["ok"] is False
    monkeypatch.setattr(hp, "can", lambda action: {"ok": True, "how": "/host/x", "why": ""})
    monkeypatch.setattr(hp, "run", lambda action: {"started": False, "how": "", "error": "exit 1"})
    r = client.post("/api/system/shutdown", headers=auth_headers)
    assert r.status_code == 502 and stopped == [False]
    monkeypatch.setattr(hp, "run", lambda action: {"started": True, "how": "/host/x", "error": ""})
    assert client.post("/api/system/reboot", headers=auth_headers).json()["action_dispatched"] is True
