"""SNMP v3 agent (owner decision, 16 Nov 2026): off by default, version 3 only with SHA-256 and AES,
read-only; the passwords are sealed and never sent back to the page."""

import asyncio
import json
import socket

import pytest

from backend.services import snmp_agent as sa

USER, AUTH, PRIV = "monitor", "auth-pass-1", "priv-pass-2"


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(sa, "STATE_FILE", str(tmp_path / "snmp.json"))
    yield tmp_path
    sa._agent.stop()


@pytest.fixture
def proc(tmp_path):
    p = tmp_path / "proc"
    (p / "1" / "net").mkdir(parents=True)
    (p / "sys" / "kernel").mkdir(parents=True)
    (p / "sys" / "kernel" / "osrelease").write_text("6.12.54-Unraid\n")
    (p / "uptime").write_text("3600.50 7000.00\n")
    (p / "loadavg").write_text("0.52 0.40 0.31 2/400 1234\n")
    (p / "meminfo").write_text(
        "MemTotal:       16000000 kB\nMemFree:  2000000 kB\nMemAvailable:   8000000 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n"
    )
    (p / "stat").write_text("cpu  100 0 100 800 0 0 0 0\ncpu0 50 0 50 400 0 0 0 0\ncpu1 50 0 50 400 0 0 0 0\n")
    (p / "1" / "net" / "dev").write_text(
        "Inter-|   Receive |  Transmit\n face |bytes packets errs drop fifo frame compressed multicast|bytes\n"
        "    lo: 100 1 0 0 0 0 0 0 100 1 0 0 0 0 0 0\n"
        "  eth0: 5000000000 10 0 0 0 0 0 0 6000 20 0 0 0 0 0 0\n"
        "vethab: 1 1 0 0 0 0 0 0 1 1 0 0 0 0 0 0\n"
    )
    return p


def test_off_by_default_and_the_passwords_stay_sealed(state):
    st = sa.public_state()
    assert st["enabled"] is False and st["port"] == 161 and st["passwords_set"] is False and st["running"] is False
    out = sa.save(False, 161, USER, AUTH, PRIV, "admin@home", "Cupboard")
    assert out["passwords_set"] and "auth" not in out and "priv" not in out
    text = (state / "snmp.json").read_text()
    assert AUTH not in text and PRIV not in text
    from backend.secret_box import unseal

    assert unseal(json.loads(text)["auth"]) == AUTH
    sa.save(False, 161, USER, None, None)  # None keeps them
    assert sa.public_state()["passwords_set"]


@pytest.mark.parametrize(
    "args,msg",
    [
        ((True, 161, "", None, None), "Fill in"),
        ((False, 161, "bad user!", None, None), "user name"),
        ((False, 161, USER, "short", PRIV), "at least 8"),
        ((False, 161, USER, AUTH, "short"), "encryption password"),
        ((True, 161, USER, AUTH, AUTH), "two different"),
        ((False, 0, USER, None, None), "port"),
    ],
)
def test_settings_that_cannot_work_are_refused(state, args, msg):
    with pytest.raises(ValueError, match=msg):
        sa.save(*args)


def test_what_it_answers(proc, tmp_path, monkeypatch, state):
    host = tmp_path / "host"
    (host / "etc").mkdir(parents=True)
    (host / "etc" / "hostname").write_text("nas\n")
    t = sa.mib(proc=str(proc), pool=str(tmp_path), started=0, host_root=str(host))
    assert str(t[sa.SYSTEM + (1, 0)]) == "Kiboto NAS, Linux 6.12.54-Unraid"
    assert str(t[sa.SYSTEM + (5, 0)]) == "nas"
    assert int(t[sa.HR + (1, 1, 0)]) == 360050  # host uptime in hundredths
    assert int(t[sa.UCD + (4, 5, 0)]) == 16000000 and int(t[sa.UCD + (4, 6, 0)]) == 8000000
    assert str(t[sa.UCD + (10, 1, 3, 1)]) == "0.52"
    # storage: memory first, then the pool
    assert str(t[sa.HR + (2, 3, 1, 3, 1)]) == "Physical memory"
    assert str(t[sa.HR + (2, 3, 1, 3, 2)]) == str(tmp_path)
    assert int(t[sa.HR + (2, 3, 1, 6, 1)]) == 8000000
    # one interface: loopback and container veths left out; 64-bit counters do not wrap
    assert int(t[(1, 3, 6, 1, 2, 1, 2, 1, 0)]) == 1
    assert str(t[sa.IF_TABLE + (2, 1)]) == "eth0"
    assert int(t[sa.IFX_TABLE + (6, 1)]) == 5000000000
    assert int(t[sa.IF_TABLE + (10, 1)]) == 5000000000 % 2**32
    # processor load from the change between two readings
    (proc / "stat").write_text("cpu  200 0 200 900 0 0 0 0\ncpu0 100 0 100 450 0 0 0 0\ncpu1 50 0 50 500 0 0 0 0\n")
    t = sa.mib(proc=str(proc), pool=str(tmp_path), started=0, host_root=str(host))
    assert int(t[sa.HR + (3, 3, 1, 2, 196608)]) == 67 and int(t[sa.HR + (3, 3, 1, 2, 196609)]) == 0


def test_the_controller_reads_walks_and_refuses_writes():
    from pysnmp.proto import rfc1905
    from pysnmp.proto.api import v2c

    tree = sa._Tree(
        lambda: {(1, 3, 6, 1, 2, 1, 1, 5, 0): v2c.OctetString("nas"), (1, 3, 6, 1, 2, 1, 1, 3, 0): v2c.TimeTicks(5)}
    )
    c = sa.controller(tree)
    assert str(c.read_variables(((1, 3, 6, 1, 2, 1, 1, 5, 0), None))[0][1]) == "nas"
    assert c.read_variables(((1, 3, 6, 1, 9), None))[0][1] is rfc1905.noSuchObject
    nxt = c.read_next_variables(((1, 3, 6, 1, 2, 1, 1), None))[0]
    assert tuple(nxt[0]) == (1, 3, 6, 1, 2, 1, 1, 3, 0)
    assert c.read_next_variables(((1, 3, 6, 1, 2, 1, 1, 5, 0), None))[0][1] is rfc1905.endOfMibView
    assert c.write_variables(((1, 3, 6, 1, 2, 1, 1, 5, 0), v2c.OctetString("x")))[0][1] is rfc1905.noSuchObject


def _free_udp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_real_v3_round_trip_and_nothing_for_v2c_or_a_wrong_password(state, monkeypatch, proc, tmp_path):
    from pysnmp.hlapi.v3arch.asyncio import (
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        UsmUserData,
        bulk_cmd,
        get_cmd,
        usmAesCfb128Protocol,
        usmHMAC192SHA256AuthProtocol,
    )

    real = sa.mib
    monkeypatch.setattr(sa, "mib", lambda: real(proc=str(proc), pool=str(tmp_path)))
    port = _free_udp_port()
    assert sa._agent.start(port, USER, AUTH, PRIV, host="127.0.0.1")
    assert sa._agent.status()["running"] and sa._agent.status()["listening_port"] == port

    async def ask():
        cli = SnmpEngine()
        target = await UdpTransportTarget.create(("127.0.0.1", port), timeout=1, retries=0)
        user = UsmUserData(
            USER, AUTH, PRIV, authProtocol=usmHMAC192SHA256AuthProtocol, privProtocol=usmAesCfb128Protocol
        )
        got = await get_cmd(cli, user, target, ContextData(), ObjectType(ObjectIdentity("1.3.6.1.2.1.1.1.0")))
        walk = await bulk_cmd(
            cli, user, target, ContextData(), 0, 10, ObjectType(ObjectIdentity("1.3.6.1.2.1.2.2.1.2"))
        )
        wrong = UsmUserData(
            USER, "wrong-pass-9", PRIV, authProtocol=usmHMAC192SHA256AuthProtocol, privProtocol=usmAesCfb128Protocol
        )
        bad = await get_cmd(cli, wrong, target, ContextData(), ObjectType(ObjectIdentity("1.3.6.1.2.1.1.1.0")))
        v2 = await get_cmd(
            cli, CommunityData("public"), target, ContextData(), ObjectType(ObjectIdentity("1.3.6.1.2.1.1.1.0"))
        )
        return got, walk, bad, v2

    got, walk, bad, v2 = asyncio.run(ask())
    assert got[0] is None and str(got[3][0][1]) == "Kiboto NAS, Linux 6.12.54-Unraid"
    assert walk[0] is None and str(walk[3][0][1]) == "eth0"
    assert bad[0] is not None  # wrong digest: no answer with data
    assert v2[0] is not None  # v1/v2c: no answer at all
    sa._agent.stop()
    assert not sa._agent.status()["running"]


def test_a_port_in_use_is_said(state):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        assert sa._agent.start(port, USER, AUTH, PRIV, host="127.0.0.1") is False
        assert f"UDP {port} could not be opened" in sa._agent.status()["error"]
        assert not sa._agent.status()["running"]


def test_apply_follows_the_settings(state, monkeypatch):
    started = []
    monkeypatch.setattr(
        sa._agent,
        "start",
        lambda port, user, auth, priv, host="0.0.0.0": started.append((port, user, auth, priv)) or True,
    )
    sa.save(True, 1161, USER, AUTH, PRIV)
    assert started == [(1161, USER, AUTH, PRIV)]
    sa._agent.error = "old"
    sa.save(False, 1161, USER, None, None)
    assert sa._agent.status()["error"] == ""
    sa.stop()


def test_routes(client, auth_headers, state, monkeypatch):
    monkeypatch.setattr(sa, "apply", lambda: {})
    assert client.get("/api/network/snmp", headers=auth_headers).json()["enabled"] is False
    body = {"enabled": True, "port": 161, "user": USER, "auth_password": AUTH, "priv_password": PRIV}
    r = client.put("/api/network/snmp", json=body, headers=auth_headers)
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["passwords_set"]
    assert client.put("/api/network/snmp", json={**body, "user": ""}, headers=auth_headers).status_code == 400


@pytest.mark.real_confirmations
def test_turning_it_on_needs_a_confirmation(client, auth_headers, state, monkeypatch):
    monkeypatch.setattr(sa, "apply", lambda: {})
    body = {"enabled": True, "port": 161, "user": USER, "auth_password": AUTH, "priv_password": PRIV}
    r = client.put("/api/network/snmp", json=body, headers=auth_headers)
    assert r.status_code == 428 and r.json()["action"] == "network.snmp"
    assert sa.public_state()["enabled"] is False
    tok = client.post(
        "/api/confirmations", json={"action": "network.snmp", "target": "UDP 161"}, headers=auth_headers
    ).json()["token"]
    r = client.put("/api/network/snmp", json=body, headers={**auth_headers, "X-Confirm-Token": tok})
    assert r.status_code == 200 and r.json()["enabled"] is True
