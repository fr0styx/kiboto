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
    assert reply == {"ok": False, "error": "host.set_name failed: hostnamectl is missing"}
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
