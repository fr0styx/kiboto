"""The clock and the SSH switch of a machine set up for Kiboto."""

import pytest

from backend import runtime
from backend.services import host_basics


@pytest.fixture
def managed(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    sshd = tmp_path / "sshd"
    sshd.write_text("")
    monkeypatch.setattr(host_basics, "SSHD", str(sshd))
    monkeypatch.setattr(host_basics, "host_name", lambda: "attic")
    monkeypatch.setattr(host_basics, "time_zone", lambda link="": "Europe/Berlin")


class Machine:
    """Answers as timedatectl and systemctl do, and keeps what it was told."""

    def __init__(self, ssh=True, ntp=True, in_step=True, can=True, refuses=()):
        self.ssh, self.ntp, self.in_step, self.can, self.refuses, self.seen = ssh, ntp, in_step, can, refuses, []

    def __call__(self, cmd, timeout=20):
        self.seen.append(cmd)
        if cmd[0] in self.refuses:
            return 1, "refused"
        yes = lambda v: "yes" if v else "no"  # noqa: E731
        if cmd[:2] == ["timedatectl", "show"]:
            return 0, f"CanNTP={yes(self.can)}\nNTP={yes(self.ntp)}\nNTPSynchronized={yes(self.in_step)}"
        if cmd[:2] == ["timedatectl", "set-ntp"]:
            self.ntp = cmd[2] == "true"
        if cmd[:2] == ["systemctl", "is-active"]:
            return (0 if self.ssh else 3), ("active\ninactive" if self.ssh else "inactive\ninactive")
        if cmd[:2] == ["systemctl", "enable"]:
            self.ssh = True
        if cmd[:2] == ["systemctl", "disable"]:
            self.ssh = False
        return 0, ""


def test_a_guest_says_these_belong_to_its_host_and_changes_nothing(client, auth_headers, monkeypatch):
    do = Machine()
    monkeypatch.setattr(host_basics, "run", do)
    assert host_basics.status() == {"managed": False}
    assert host_basics.set_ssh(False) is False and host_basics.set_clock_automatic(False) is False
    assert client.get("/api/system/machine", headers=auth_headers).json() == {"managed": False}
    r = client.put("/api/system/machine", headers=auth_headers, json={"ssh": False})
    assert r.status_code == 409
    assert do.seen == []


def test_the_machine_says_how_it_stands(managed, client, auth_headers, monkeypatch):
    monkeypatch.setattr(host_basics, "run", Machine(ssh=True, ntp=True, in_step=False))
    assert client.get("/api/system/machine", headers=auth_headers).json() == {
        "managed": True,
        "host_name": "attic",
        "time_zone": "Europe/Berlin",
        "clock": {"can": True, "automatic": True, "in_step": False},
        "ssh": {"installed": True, "on": True},
    }


def test_a_machine_without_an_ssh_server_says_so(managed, monkeypatch, tmp_path):
    monkeypatch.setattr(host_basics, "SSHD", str(tmp_path / "missing"))
    do = Machine()
    assert host_basics.ssh(do) == {"installed": False, "on": False}
    assert host_basics.set_ssh(True, do) is False
    assert do.seen == []


def test_a_clock_that_cannot_be_asked_reads_as_not_set(managed):
    assert host_basics.clock(Machine(refuses=("timedatectl",))) == {"can": False, "automatic": False, "in_step": False}


def test_ssh_goes_off_at_once_and_stays_off_at_the_next_start(managed, client, auth_headers, monkeypatch):
    do = Machine(ssh=True)
    monkeypatch.setattr(host_basics, "run", do)
    r = client.put("/api/system/machine", headers=auth_headers, json={"ssh": False})
    assert r.status_code == 200 and r.json()["ssh"] == {"installed": True, "on": False}
    assert ["systemctl", "disable", "--now", "ssh.service", "ssh.socket"] in do.seen


@pytest.mark.real_confirmations
def test_turning_ssh_on_is_asked_first(managed, client, auth_headers, monkeypatch):
    do = Machine(ssh=False)
    monkeypatch.setattr(host_basics, "run", do)
    r = client.put("/api/system/machine", headers=auth_headers, json={"ssh": True})
    assert r.status_code == 428 and r.json()["action"] == "system.ssh_on" and do.ssh is False
    token = client.post(
        "/api/confirmations", headers=auth_headers, json={"action": "system.ssh_on", "target": "attic"}
    ).json()["token"]
    r = client.put("/api/system/machine", headers={**auth_headers, "X-Confirm-Token": token}, json={"ssh": True})
    assert r.status_code == 200 and r.json()["ssh"]["on"] is True
    assert ["systemctl", "enable", "--now", "ssh.service"] in do.seen


def test_the_clock_switch(managed, client, auth_headers, monkeypatch):
    do = Machine(ntp=True)
    monkeypatch.setattr(host_basics, "run", do)
    r = client.put("/api/system/machine", headers=auth_headers, json={"clock_automatic": False})
    assert r.status_code == 200 and r.json()["clock"]["automatic"] is False
    assert ["timedatectl", "set-ntp", "false"] in do.seen
    r = client.put("/api/system/machine", headers=auth_headers, json={"clock_automatic": True})
    assert r.json()["clock"]["automatic"] is True


def test_a_change_the_machine_refuses_is_said(managed, client, auth_headers, monkeypatch):
    monkeypatch.setattr(host_basics, "run", Machine(refuses=("systemctl",)))
    r = client.put("/api/system/machine", headers=auth_headers, json={"ssh": False})
    assert r.status_code == 502 and r.json()["detail"] == "The machine did not take the change."


def test_only_an_administrator_changes_the_machine(managed, client, monkeypatch):
    monkeypatch.setattr(host_basics, "run", Machine())
    assert client.put("/api/system/machine", json={"ssh": False}).status_code in (401, 403)
