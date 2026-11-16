"""Audit A13: the host firewall, off by default, managed only where Kiboto owns the host's network."""

import pytest

from backend.services import firewall


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setattr(firewall, "STATE_FILE", str(tmp_path / "firewall.json"))
    monkeypatch.setattr(firewall, "_owns", lambda: False)


class Run:
    def __init__(self, rc=0, err=""):
        self.calls, self.rc, self.err = [], rc, err

    def __call__(self, cmd, input, **kw):
        self.calls.append((cmd, input))
        return type("R", (), {"returncode": self.rc, "stderr": self.err})()


def test_off_by_default_and_this_page_always_reachable():
    st = firewall.state()
    assert st["enabled"] is False and st["allow_from"] == "lan" and st["services"]["web"] is True
    rules = firewall.ruleset({**st, "services": {**st["services"], "web": False, "ssh": False}})
    assert "policy drop" in rules and "ct state established,related accept" in rules
    assert "tcp dport { 8082 } accept  # web" in rules and "# ssh" not in rules
    assert "192.168.0.0/16" in rules and rules.startswith("table inet kiboto\ndelete table inet kiboto\n")


def test_anywhere_opens_the_kept_services_to_every_address():
    st = {**firewall.state(), "allow_from": "anywhere"}
    rules = firewall.ruleset(st)
    assert "tcp dport { 139, 445 } accept  # smb" in rules and "udp dport { 41641 } accept  # tailscale" in rules
    assert "tcp dport { 8082 } accept  # web from anywhere" in rules
    assert "# nfs" not in rules


def test_in_a_container_it_says_why_and_refuses_to_turn_on(monkeypatch):
    assert firewall.capability() == (False, "host")
    with pytest.raises(ValueError, match="can't manage"):
        firewall.save(True, "lan", {})
    run = Run()
    st = firewall.save(False, "anywhere", {"nfs": True, "web": False, "bogus": True}, run=run)
    assert st["allow_from"] == "anywhere" and st["services"]["nfs"] is True and st["services"]["web"] is True
    assert "bogus" not in st["services"] and run.calls == []  # nothing applied where it can't be
    with pytest.raises(ValueError, match="home network or anywhere"):
        firewall.save(False, "everyone", {})


def test_where_kiboto_owns_the_firewall_it_loads_and_removes_its_table(monkeypatch, tmp_path):
    monkeypatch.setattr(firewall, "_owns", lambda: True)
    monkeypatch.setattr(firewall.shutil, "which", lambda name: None)
    assert firewall.capability() == (False, "no_nft")
    monkeypatch.setattr(firewall.shutil, "which", lambda name: "/usr/sbin/nft")
    status = tmp_path / "status"
    status.write_text("Name:\tpython\nCapEff:\t0000000000000000\n")
    real_open = open
    monkeypatch.setattr(
        "builtins.open",
        lambda p, *a, **k: real_open(status, *a, **k) if p == "/proc/self/status" else real_open(p, *a, **k),
    )
    assert firewall.capability() == (False, "no_cap")
    status.write_text("CapEff:\t0000000000001000\n")
    assert firewall.capability() == (True, "")
    run = Run()
    firewall.save(True, "lan", {"ssh": False}, run=run)
    assert (
        run.calls[-1][0] == ["nft", "-f", "-"] and "policy drop" in run.calls[-1][1] and "# ssh" not in run.calls[-1][1]
    )
    firewall.reapply_at_start(run=run)
    assert len(run.calls) == 2
    firewall.save(False, "lan", {}, run=run)
    assert run.calls[-1][1] == "table inet kiboto\ndelete table inet kiboto\n"
    with pytest.raises(RuntimeError, match="could not be loaded: bad rule"):
        firewall.save(True, "lan", {}, run=Run(rc=1, err="bad rule"))


def test_routes(client, auth_headers):
    res = client.get("/api/security/firewall", headers=auth_headers).json()
    assert (
        res["enabled"] is False
        and res["possible"] is False
        and res["why_not"] == "host"
        and "policy drop" in res["rules"]
    )
    bad = client.put("/api/security/firewall", headers=auth_headers, json={"enabled": True})
    assert bad.status_code == 400 and "can't manage" in bad.json()["detail"]
    ok = client.put(
        "/api/security/firewall",
        headers=auth_headers,
        json={"enabled": False, "allow_from": "lan", "services": {"webdav": True}},
    )
    assert ok.status_code == 200 and ok.json()["services"]["webdav"] is True


def test_the_setting_is_read_through_settings():
    from backend.config import SETTINGS

    assert SETTINGS.owns_firewall is False
