"""Audit A13: the host firewall, off by default. On means: the home network reaches everything on
the machine, the outside reaches only what is ticked. Managed where Kiboto owns the machine."""

import pytest

from backend import runtime
from backend.services import firewall

REAL_OWNS, REAL_NFT = firewall._owns, firewall._nft  # every test below is given pretend ones

# /proc/net/if_inet6: address, interface index, prefix length, scope, flags, name
IF_INET6 = """\
00000000000000000000000000000001 01 80 10 80       lo
fe800000000000005054000000000001 02 40 20 80   enp1s0
2a0104f8000100020000000000000005 02 40 00 00   enp1s0
fd00000000000000000000000000beef 02 40 00 00   enp1s0
2a0104f8000100030000000000000009 03 80 00 00   enp2s0
nonsense
"""


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setattr(firewall, "STATE_FILE", str(tmp_path / "firewall.json"))
    monkeypatch.setattr(firewall, "_owns", lambda: False)
    monkeypatch.setattr(firewall, "_nft", lambda: "nft")
    monkeypatch.setattr(firewall, "IF_INET6", str(tmp_path / "no-if_inet6"))
    monkeypatch.setitem(firewall._loaded, "text", "")


class Run:
    def __init__(self, rc=0, err=""):
        self.calls, self.rc, self.err = [], rc, err

    def __call__(self, cmd, input, **kw):
        self.calls.append((cmd, input))
        return type("R", (), {"returncode": self.rc, "stderr": self.err})()


@pytest.fixture
def owned(monkeypatch, tmp_path):
    """Kiboto owns the firewall and this process may load rules."""
    monkeypatch.setattr(firewall, "_owns", lambda: True)
    status = tmp_path / "status"
    status.write_text("CapEff:\t0000000000001000\n")
    real_open = open
    monkeypatch.setattr(
        "builtins.open",
        lambda p, *a, **k: real_open(status, *a, **k) if p == "/proc/self/status" else real_open(p, *a, **k),
    )
    return status


def test_off_by_default_and_nothing_is_open_to_the_outside():
    st = firewall.state()
    assert st == {"enabled": False, "outside": dict.fromkeys(firewall.SERVICE_IDS, False)}
    rules = firewall.ruleset(st)
    assert rules.startswith("table inet kiboto\ndelete table inet kiboto\n")
    assert "policy drop" in rules and "ct state established,related accept" in rules
    assert "dport" not in rules and "accept  # " not in rules.split("the home network")[-1]


def test_the_home_network_reaches_everything_whatever_is_ticked():
    rules = firewall.ruleset(firewall.state())
    assert "ip saddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10 } accept  # the home network" in rules
    assert "ip6 saddr { fc00::/7, fe80::/10 } accept  # the home network" in rules
    # no port is named for home: a service nobody listed (a new app, NFS's extra ports) still answers
    home = [line for line in rules.splitlines() if "the home network" in line]
    assert len(home) == 2 and not any("dport" in line for line in home)


def test_the_outside_reaches_only_what_is_ticked():
    st = firewall.cleaned({"enabled": True, "outside": {"web": True, "smb": True, "nfs": True, "tailscale": True}})
    rules = firewall.ruleset(st)
    assert "tcp dport { 8082, 8443 } accept  # web, from outside" in rules  # this page, plain and HTTPS
    assert "tcp dport { 139, 445 } accept  # smb, from outside" in rules
    assert "tcp dport { 111, 2049 } accept  # nfs, from outside" in rules
    assert "udp dport { 111, 2049 } accept  # nfs, from outside" in rules
    assert "udp dport { 41641 } accept  # tailscale, from outside" in rules
    assert "# ssh" not in rules and "{ 22 }" not in rules and "2222" not in rules
    opened = [line for line in rules.splitlines() if "accept" in line and "from outside" in line]
    assert len(opened) == 5 and not any("saddr" in line for line in opened)


def test_an_apps_published_port_is_closed_to_the_outside_unless_apps_is_ticked():
    """Docker forwards a published port to its container: the input rules never see it."""
    rules = firewall.ruleset(firewall.cleaned({"enabled": True, "outside": {}}))
    forward = rules[rules.index("  chain forward {") :]
    assert "type filter hook forward priority -1; policy accept;" in forward
    assert "ct state established,related accept" in forward
    # only a connection whose address was rewritten for a published port, and only from outside
    drops = [line.strip() for line in forward.splitlines() if " drop" in line]
    assert drops == [
        "ct status dnat ip saddr != { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10 } drop"
        "  # an app's published port, from outside",
        "ct status dnat ip6 saddr != { fc00::/7, fe80::/10 } drop  # an app's published port, from outside",
    ]
    ticked = firewall.ruleset(firewall.cleaned({"enabled": True, "outside": {"apps": True}}))
    assert "chain forward" not in ticked and "dnat" not in ticked
    assert "dport" not in ticked  # apps has no port of its own to open


def test_only_a_plain_true_opens_something_and_unknown_names_are_dropped():
    st = firewall.cleaned({"enabled": "yes", "outside": {"ssh": 1, "smb": "true", "web": True, "telnet": True}})
    assert st["enabled"] is False
    assert st["outside"] == {**dict.fromkeys(firewall.SERVICE_IDS, False), "web": True}
    assert firewall.cleaned({"enabled": True, "outside": ["ssh"]})["outside"]["ssh"] is False


def test_the_public_ipv6_network_this_machine_is_on_is_home(tmp_path, monkeypatch):
    table = tmp_path / "if_inet6"
    table.write_text(IF_INET6)
    monkeypatch.setattr(firewall, "IF_INET6", str(table))
    # the /64 with a public address; not the private one (in the fixed list), not a lone /128
    assert firewall.onlink6() == ("2a01:4f8:1:2::/64",)
    assert "ip6 saddr { fc00::/7, fe80::/10, 2a01:4f8:1:2::/64 } accept" in firewall.ruleset(firewall.state())
    assert firewall.is_home("2a01:4f8:1:2::77") and not firewall.is_home("2a01:4f8:1:3::77")


@pytest.mark.parametrize(
    "address, at_home",
    [
        ("192.168.1.20", True),
        ("10.0.2.2", True),
        ("100.101.102.103", True),  # Tailscale
        ("127.0.0.1", True),
        ("::1", True),
        ("fe80::1%enp1s0", True),
        ("fd12::5", True),
        ("::ffff:192.168.1.20", True),
        ("203.0.113.9", False),
        ("::ffff:203.0.113.9", False),
        ("2001:db8::1", False),
        ("testclient", True),  # not an address: never a reason to refuse
    ],
)
def test_which_addresses_are_home(address, at_home):
    assert firewall.is_home(address) is at_home


def test_in_a_container_it_says_why_and_refuses_to_turn_on():
    assert firewall.capability() == (False, "host")
    with pytest.raises(ValueError, match="can't manage"):
        firewall.save(True, {})
    run = Run()
    st = firewall.save(False, {"nfs": True, "bogus": True}, run=run)
    assert st["outside"]["nfs"] is True and "bogus" not in st["outside"]
    assert run.calls == []  # nothing applied where it can't be
    assert firewall.state() == st


def test_where_kiboto_owns_the_firewall_it_loads_and_removes_its_table(owned, monkeypatch):
    monkeypatch.setattr(firewall, "_nft", lambda: "")
    assert firewall.capability() == (False, "no_nft")
    monkeypatch.setattr(firewall, "_nft", lambda: "/usr/sbin/nft")
    owned.write_text("Name:\tpython\nCapEff:\t0000000000000000\n")
    assert firewall.capability() == (False, "no_cap")
    owned.write_text("CapEff:\t0000000000001000\n")
    assert firewall.capability() == (True, "")
    run = Run()
    firewall.save(True, {"ssh": True}, run=run)
    cmd, script = run.calls[-1]
    assert cmd == ["/usr/sbin/nft", "-f", "-"] and "policy drop" in script and "# ssh, from outside" in script
    firewall.reapply_at_start(run=run)
    assert len(run.calls) == 2
    firewall.save(False, {}, run=run)
    assert run.calls[-1][1] == "table inet kiboto\ndelete table inet kiboto\n"
    assert firewall.state()["outside"]["ssh"] is True  # what was ticked is kept while it is off
    with pytest.raises(RuntimeError, match="could not be loaded: bad rule"):
        firewall.save(True, {}, run=Run(rc=1, err="bad rule"))
    assert firewall.state()["enabled"] is False  # rules that did not load are not kept as on


def test_a_machine_kiboto_runs_owns_its_firewall_without_any_setting(monkeypatch, tmp_path):
    assert REAL_OWNS() is False
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    assert REAL_OWNS() is True


def test_nft_is_found_where_debian_keeps_it_even_off_the_path(monkeypatch, tmp_path):
    monkeypatch.setattr(firewall.shutil, "which", lambda name: None)
    there = tmp_path / "nft"
    there.write_text("")
    monkeypatch.setattr(firewall, "NFT_PLACES", (str(tmp_path / "missing"), str(there)))
    assert REAL_NFT() == str(there)
    monkeypatch.setattr(firewall, "NFT_PLACES", ())
    assert REAL_NFT() == ""
    monkeypatch.setattr(firewall.shutil, "which", lambda name: "/usr/bin/nft")
    assert REAL_NFT() == "/usr/bin/nft"


def test_with_a_host_door_the_web_process_needs_no_permission_of_its_own(owned, monkeypatch):
    owned.write_text("CapEff:\t0000000000000000\n")
    asked = []
    monkeypatch.setattr(firewall.door, "available", lambda *a: True)
    monkeypatch.setattr(firewall.door, "call", lambda op, **args: asked.append((op, args)))
    assert firewall.capability() == (True, "")
    st = firewall.save(True, {"web": True})
    assert asked == [("firewall.apply", {"st": st})]
    firewall.reapply_at_start()
    assert len(asked) == 2


def test_the_door_loads_only_what_the_page_offers(owned, monkeypatch):
    from backend.services import host_door

    assert host_door.OPERATIONS["firewall.apply"].args == {"st": (dict,)}
    loaded = []
    monkeypatch.setattr(firewall, "_load", lambda st, run=None: loaded.append(st))
    sent = {"enabled": True, "outside": {"ssh": True, "telnet": True}, "table": "filter; flush ruleset"}
    assert host_door.handle({"op": "firewall.apply", "args": {"st": sent}}, 0)["ok"] is True
    assert loaded == [{"enabled": True, "outside": {**dict.fromkeys(firewall.SERVICE_IDS, False), "ssh": True}}]
    script = firewall.ruleset(loaded[0])
    assert "# ssh, from outside" in script and "telnet" not in script and "flush" not in script


def test_turning_it_on_from_outside_without_this_page_ticked_is_refused(owned):
    run = Run()
    with pytest.raises(ValueError, match="shut yourself out") as refused:
        firewall.save(True, {"ssh": True}, run=run, asked_from="203.0.113.9")
    assert refused.value.text == {"msg_key": "srv.fw_outside_self", "params": {}}
    assert run.calls == [] and firewall.state()["enabled"] is False
    assert firewall.save(True, {"web": True}, run=run, asked_from="203.0.113.9")["enabled"] is True
    assert firewall.save(True, {"web": False}, run=run, asked_from="192.168.1.20")["outside"]["web"] is False
    # turning it off is never refused, from anywhere
    assert firewall.save(False, {}, run=run, asked_from="203.0.113.9")["enabled"] is False


def test_settings_kept_by_the_version_before_open_nothing_new_to_the_outside(tmp_path):
    from backend.fsutil import atomic_write_json

    old = {"web": True, "ssh": True, "smb": True, "nfs": False, "tailscale": True, "mdns": True}
    atomic_write_json(firewall.STATE_FILE, {"enabled": True, "allow_from": "lan", "services": old})
    st = firewall.state()
    assert st["enabled"] is True and not any(st["outside"].values())  # "home only" stays home only
    atomic_write_json(firewall.STATE_FILE, {"enabled": True, "allow_from": "anywhere", "services": old})
    st = firewall.state()
    assert st["outside"] == {
        "web": True,
        "ssh": True,
        "smb": True,
        "nfs": False,
        "webdav": False,
        "sftp": False,
        "tailscale": True,
        "apps": True,  # that version never closed them
    }
    atomic_write_json(firewall.STATE_FILE, ["not", "settings"])
    assert firewall.state()["enabled"] is False


def test_the_rules_are_loaded_again_when_the_home_network_changes(owned, tmp_path, monkeypatch):
    table = tmp_path / "if_inet6"
    table.write_text(IF_INET6)
    monkeypatch.setattr(firewall, "IF_INET6", str(table))
    run = Run()
    assert firewall.keep_current(run=run) is False  # off: nothing to keep
    firewall.save(True, {}, run=run)
    assert firewall.keep_current(run=run) is False and len(run.calls) == 1  # as loaded
    table.write_text(IF_INET6.replace("2a0104f800010002", "2a0104f8000100aa"))  # the provider moved the home
    assert firewall.keep_current(run=run) is True
    assert "2a01:4f8:1:aa::/64" in run.calls[-1][1] and "2a01:4f8:1:2::/64" not in run.calls[-1][1]
    assert firewall.keep_current(run=run) is False


def test_the_watch_loop_checks_and_survives_a_failure(monkeypatch):
    waits, calls = [], []

    def check():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("the rules could not be loaded")
        return True

    monkeypatch.setattr(firewall, "keep_current", check)
    firewall.watch(sleep=waits.append, rounds=2)
    assert waits == [firewall.CHECK_EVERY_SECS] * 2 and len(calls) == 2


def test_routes(client, auth_headers):
    res = client.get("/api/security/firewall", headers=auth_headers).json()
    assert res["enabled"] is False and res["possible"] is False and res["why_not"] == "host"
    assert "policy drop" in res["rules"] and "192.168.0.0/16" in res["home"] and "fe80::/10" in res["home"]
    bad = client.put("/api/security/firewall", headers=auth_headers, json={"enabled": True})
    assert bad.status_code == 400 and "can't manage" in bad.json()["detail"]
    ok = client.put(
        "/api/security/firewall", headers=auth_headers, json={"enabled": False, "outside": {"webdav": True}}
    )
    assert ok.status_code == 200 and ok.json()["outside"]["webdav"] is True
    # the shape of the version before opens nothing
    old = client.put(
        "/api/security/firewall",
        headers=auth_headers,
        json={"enabled": False, "allow_from": "anywhere", "services": {"ssh": True}},
    )
    assert old.status_code == 200 and old.json()["outside"]["ssh"] is False


def test_a_failure_to_load_reaches_the_page_with_its_reason(client, auth_headers, owned, monkeypatch):
    def fails(st, run=None):
        raise RuntimeError("The firewall rules could not be loaded: Error: syntax error")

    monkeypatch.setattr(firewall, "_load", fails)
    res = client.put("/api/security/firewall", headers=auth_headers, json={"enabled": True})
    assert res.status_code == 502 and "syntax error" in res.json()["detail"]


def test_the_setting_is_read_through_settings():
    from backend.config import SETTINGS

    assert SETTINGS.owns_firewall is False


def test_the_installer_brings_nft():
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "packaging", "install.sh"), encoding="utf-8") as f:
        text = f.read()
    tools = text[text.index('TOOLS="') : text.index('"\n', text.index('TOOLS="'))]
    assert " nftables " in tools.replace("\\\n", " ") + " "
