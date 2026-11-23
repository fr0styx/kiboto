"""The host door (ADR 0006): a fixed list of operations behind a socket, for root and the web user only."""

import json
import os
import socket
import threading

import pytest

from backend import door
from backend.services import host_basics, host_door


@pytest.fixture
def audit(tmp_path, monkeypatch):
    monkeypatch.setattr(host_door, "AUDIT", str(tmp_path / "door-audit.log"))
    return tmp_path / "door-audit.log"


def _lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


def test_only_listed_operations_with_exactly_their_arguments(audit, monkeypatch):
    assert host_door.handle({"op": "door.ping", "args": {}}, 0) == {"ok": True, "result": "pong"}
    for bad, why in (
        ({"op": "shell", "args": {"cmd": "rm -rf /"}}, "no such operation"),
        ({"op": "host.set_ssh", "args": {}}, "takes on"),
        ({"op": "host.set_ssh", "args": {"on": True, "extra": 1}}, "takes on"),
        ({"op": "host.set_ssh", "args": {"on": 1}}, "must be bool"),
        ({"op": "host.set_name", "args": {"name": "x" * 64}}, "too long"),
        ({"op": "host.set_name", "args": {"name": "a\x00b"}}, "too long"),
        ("not a dict", "not a request"),
        (None, "not a request"),
    ):
        reply = host_door.handle(bad, 1000)
        assert reply["ok"] is False and why in reply["error"], (bad, reply)
    assert [x["outcome"] for x in _lines(audit)] == ["done"] + ["refused"] * 8


def test_an_operation_runs_kibotos_own_function_and_a_failure_is_said(audit, monkeypatch):
    seen = []
    monkeypatch.setattr(host_basics, "set_ssh", lambda on: seen.append(on) or True)
    assert host_door.handle({"op": "host.set_ssh", "args": {"on": False}}, 0) == {"ok": True, "result": True}
    assert seen == [False]

    def broken(name):
        raise OSError("hostnamectl is missing")

    monkeypatch.setattr(host_basics, "set_host_name", broken)
    reply = host_door.handle({"op": "host.set_name", "args": {"name": "nas"}}, 0)
    assert reply == {"ok": False, "error": "hostnamectl is missing", "kind": "other", "text": None}
    assert _lines(audit)[-1]["outcome"] == "failed"


@pytest.fixture
def running_door(tmp_path, audit, monkeypatch):
    path = os.path.join("/tmp", f"kb-door-test-{os.getpid()}.sock")
    server = host_door.listen(path)
    monkeypatch.setattr(host_door, "allowed_uids", lambda: {os.getuid()})
    uids = {os.getuid()}

    def loop():
        for _ in range(3):
            try:
                conn, _ = server.accept()
            except OSError:
                return
            host_door._serve_one(conn, uids)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    yield path
    server.close()
    if os.path.exists(path):
        os.remove(path)


def test_a_call_goes_through_the_socket_and_back(running_door):
    assert oct(os.stat(running_door).st_mode & 0o777) == "0o660"
    assert door.call("door.ping", sock=running_door) == "pong"
    with pytest.raises(door.DoorError, match="no such operation"):
        door.call("format.everything", sock=running_door)


def test_someone_else_is_turned_away(tmp_path, audit):
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with b:
        host_door._serve_one(a, {12345678})  # this test's uid is not among them
        assert json.loads(b.recv(4096)) == {"ok": False, "error": "not allowed"}
    assert _lines(audit)[-1] == {**_lines(audit)[-1], "op": "?", "outcome": "refused"}


def test_the_door_is_used_where_it_runs_and_not_inside_itself(monkeypatch, tmp_path):
    sock = tmp_path / "door.sock"
    sock.write_text("")
    monkeypatch.setattr(door, "SOCK", str(sock))
    monkeypatch.delenv(door.IN_DOOR, raising=False)
    assert door.available(str(sock)) and not door.available(str(tmp_path / "none"))
    monkeypatch.setenv(door.IN_DOOR, "1")
    assert not door.available(str(sock))


def test_the_machines_settings_go_through_the_door_when_it_is_there(monkeypatch):
    calls = []
    monkeypatch.setattr(host_basics.door, "available", lambda: True)
    monkeypatch.setattr(host_basics.door, "call", lambda op, **a: calls.append((op, a)) or True)
    assert host_basics.set_host_name("nas") is True
    assert host_basics.set_time_zone("Europe/Berlin") is True
    assert host_basics.set_clock_automatic(1) is True
    assert host_basics.set_ssh(False) is True
    assert calls == [
        ("host.set_name", {"name": "nas"}),
        ("host.set_time_zone", {"zone": "Europe/Berlin"}),
        ("host.set_clock_automatic", {"on": True}),
        ("host.set_ssh", {"on": False}),
    ]


def test_a_refusal_is_false_and_a_door_that_does_not_answer_is_done_here(monkeypatch):
    monkeypatch.setattr(host_basics.door, "available", lambda: True)

    def refused(op, **a):
        raise door.DoorError("host.set_name failed: no")

    monkeypatch.setattr(host_basics.door, "call", refused)
    assert host_basics._door("host.set_name", name="nas") is False

    def gone(op, **a):
        raise ConnectionRefusedError("no door")

    monkeypatch.setattr(host_basics.door, "call", gone)
    assert host_basics._door("host.set_name", name="nas") is None
    monkeypatch.setattr(host_basics.door, "available", lambda: False)
    assert host_basics._door("host.set_name", name="nas") is None


def test_a_bad_answer_from_the_door_is_an_error(monkeypatch):
    class Sock:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, t):
            pass

        def connect(self, p):
            pass

        def sendall(self, b):
            pass

        def recv(self, n):
            return b"not json\n"

    monkeypatch.setattr(door.socket, "socket", Sock)
    with pytest.raises(door.DoorError, match="no answer"):
        door.call("door.ping")


def test_the_service_files_follow_the_running_version(tmp_path):
    rel = tmp_path / "rel"
    (rel / "packaging").mkdir(parents=True)
    for name in ("kiboto.service", "kiboto-door.service"):
        (rel / "packaging" / name).write_text(f"[Unit]\nDescription={name}\n")
    units = tmp_path / "units"
    units.mkdir()
    (units / "kiboto.service").write_text("[Unit]\nDescription=old\n")
    ran = []

    def run(cmd, timeout=60, cwd=None, env=None):
        ran.append(cmd)
        return 0, ""

    from backend.services import native_update

    assert native_update.ensure_units(str(rel), run, str(units)) == ["kiboto.service", "kiboto-door.service"]
    assert (units / "kiboto-door.service").read_text().endswith("kiboto-door.service\n")
    assert ran[:2] == [
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable", "-q", "kiboto.service", "kiboto-door.service"],
    ]
    assert ran[-1] == ["systemctl", "restart", "kiboto-door.service"]
    ran.clear()
    assert native_update.ensure_units(str(rel), run, str(units)) == []
    assert ran == [["systemctl", "restart", "kiboto-door.service"]]  # the door runs this version again


def test_a_refusal_comes_back_as_the_same_kind_with_its_words(audit, monkeypatch):
    from backend.errors import SaidError
    from backend.hardware.net import managed

    def refuses(key=None):
        raise SaidError("That is not the change being tried.", "net_not_this")

    monkeypatch.setattr(managed, "keep", refuses)
    reply = host_door.handle({"op": "network.keep", "args": {"key": "k" * 20}}, 0)
    assert reply["ok"] is False and reply["kind"] == "value" and reply["text"]["msg_key"] == "srv.net_not_this"
    err = door.DoorError(reply["error"], reply["kind"], reply["text"]).as_error()
    assert (
        isinstance(err, ValueError) and err.text == reply["text"] and str(err) == "That is not the change being tried."
    )
    assert isinstance(door.DoorError("x", "runtime").as_error(), RuntimeError)
    other = door.DoorError("x", "other")
    assert other.as_error() is other
    assert host_door.handle({"op": "network.keep", "args": {"key": None}}, 0)["kind"] == "value"  # None is allowed
    assert "must be str or NoneType" in host_door.handle({"op": "network.keep", "args": {"key": 5}}, 0)["error"]


def test_via_uses_the_door_where_it_runs_and_this_process_elsewhere(monkeypatch):
    here = []
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: False)
    assert door.via("network.settle", lambda: here.append(1) or True) is True and here == [1]
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: {"op": op, **a})
    assert door.via("network.keep", lambda key: "here", key="abc") == {"op": "network.keep", "key": "abc"}

    def refused(op, **a):
        raise door.DoorError("The bridge is already there.", "value")

    monkeypatch.setattr(door, "call", refused)
    with pytest.raises(ValueError, match="already there"):
        door.via("network.try_bridge", lambda **a: None, on=True, port="eth0", now={})

    def gone(op, **a):
        raise FileNotFoundError("no socket")

    monkeypatch.setattr(door, "call", gone)
    assert door.via("network.settle", lambda: "done here") == "done here"


def test_the_network_and_firewall_operations_run_kibotos_own_code(audit, monkeypatch):
    from backend.hardware.net import managed
    from backend.services import firewall

    seen = []
    monkeypatch.setattr(managed, "start_trial", lambda changes: seen.append(("trial", changes)) or {"status": "trying"})
    monkeypatch.setattr(managed, "start_bridge_trial", lambda on, port, now: seen.append(("bridge", on, port)) or {})
    monkeypatch.setattr(managed, "go_back", lambda key: seen.append(("back", key)) or {"reverted": True})
    monkeypatch.setattr(managed, "settle", lambda: seen.append(("settle",)) or False)
    monkeypatch.setattr(managed, "ensure_fallback", lambda: seen.append(("fallback",)) or True)
    monkeypatch.setattr(firewall, "apply", lambda st: seen.append(("fw", st)))
    assert host_door.handle({"op": "network.try_address", "args": {"changes": {"iface": "eth0"}}}, 0)["ok"]
    assert host_door.handle({"op": "network.try_bridge", "args": {"on": True, "port": "eth0", "now": {}}}, 0)["ok"]
    assert host_door.handle({"op": "network.go_back", "args": {"key": None}}, 0)["ok"]
    assert host_door.handle({"op": "network.settle", "args": {}}, 0)["ok"]
    assert host_door.handle({"op": "network.ensure_fallback", "args": {}}, 0)["ok"]
    sent = {"enabled": True, "allow_from": "everywhere; drop table", "services": {"smb": False, "evil": True}, "x": 1}
    assert host_door.handle({"op": "firewall.apply", "args": {"st": sent}}, 0)["ok"]
    fw = seen[-1][1]
    assert fw["enabled"] is True and fw["allow_from"] == "lan" and "evil" not in fw["services"] and "x" not in fw
    assert fw["services"]["smb"] is False and fw["services"]["web"] is True
    assert [x[0] for x in seen] == ["trial", "bridge", "back", "settle", "fallback", "fw"]


def test_the_firewall_and_the_network_page_go_through_the_door(monkeypatch):
    import subprocess

    from backend.hardware.net import host
    from backend.services import firewall

    calls = []
    monkeypatch.setattr(door, "via", lambda op, here, **a: calls.append((op, sorted(a))) or {"status": "ok"})
    firewall.apply({"enabled": False}, run=subprocess.run)
    assert calls[-1] == ("firewall.apply", ["st"])
    loaded = []
    firewall.apply(
        {"enabled": False, "allow_from": "lan", "services": {}},
        run=lambda *a, **k: loaded.append(1) or subprocess.CompletedProcess(a, 0, "", ""),
    )
    assert loaded == [1] and len(calls) == 1  # a test's runner: never the door
    monkeypatch.setattr("backend.hardware.net.managed.networkd_runs", lambda do=None: True)
    page = host.ManagedHostNetwork()
    for changes, op in (
        ({"confirm": "k"}, "network.keep"),
        ({"revert": "k"}, "network.go_back"),
        ({"iface": "eth0"}, "network.try_address"),
    ):
        page.apply("address", "", changes)
        assert calls[-1][0] == op


def test_a_door_of_the_version_before_that_lacks_an_operation_means_doing_it_here(monkeypatch):
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)

    def older(op, **a):
        raise door.DoorError(f"no such operation: {op}")  # what a door from before step 2 answers

    monkeypatch.setattr(door, "call", older)
    assert door.via("network.settle", lambda: "done here") == "done here"
