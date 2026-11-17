"""Restart and Shut down: why they cannot work here comes with its message key, so the page and a
refused request show it in the reader's language."""

from backend.services import host_power


def test_the_reason_carries_its_key(monkeypatch):
    monkeypatch.setattr(host_power, "test_mode", lambda: False)
    monkeypatch.setattr(host_power, "commands", lambda action: [])
    monkeypatch.setattr(host_power, "in_container", lambda: True)
    got = host_power.can("reboot")
    assert got["ok"] is False and got["text"] == {"msg_key": "srv.power_no_host_command", "params": {"name": "reboot"}}
    assert "/host/reboot" in got["why"]
    monkeypatch.setattr(host_power, "in_container", lambda: False)
    assert host_power.can("shutdown")["text"]["msg_key"] == "srv.power_no_command"


def test_a_refused_restart_answers_with_the_key(client, auth_headers, monkeypatch):
    monkeypatch.setattr(host_power, "test_mode", lambda: False)
    monkeypatch.setattr(host_power, "commands", lambda action: [])
    monkeypatch.setattr(host_power, "in_container", lambda: True)
    r = client.post("/api/system/reboot", headers=auth_headers)
    body = r.json()
    assert r.status_code == 409 and body["error"] == "power_not_here"
    assert body["text"]["msg_key"] == "srv.power_no_host_command"
