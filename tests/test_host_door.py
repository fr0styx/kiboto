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


def test_someone_else_is_turned_away(tmp_path, audit, monkeypatch):
    monkeypatch.setattr(host_door, "allowed_uids", lambda: {12345678})  # looked up again: still not this test
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
    sent = {"enabled": True, "outside": {"smb": True, "ssh": "yes; drop table", "evil": True}, "x": 1}
    assert host_door.handle({"op": "firewall.apply", "args": {"st": sent}}, 0)["ok"]
    fw = seen[-1][1]
    assert fw["enabled"] is True and set(fw) == {"enabled", "outside"} and "evil" not in fw["outside"]
    assert fw["outside"]["smb"] is True and fw["outside"]["ssh"] is False and fw["outside"]["web"] is False
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
        {"enabled": False, "outside": {}},
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


def test_account_numbers_must_be_kibotos_whatever_the_web_process_sends(audit, monkeypatch):
    from backend.services import samba_host

    seen = []
    monkeypatch.setattr(samba_host, "reload", lambda changed, numbers: seen.append(numbers) or True)
    monkeypatch.setattr(samba_host, "set_password", lambda name, number, password: seen.append(number) or True)
    ok = host_door.handle({"op": "samba.reload", "args": {"changed": None, "numbers": {"ana": 20001}}}, 0)
    assert ok["ok"] and seen == [{"ana": 20001}]
    for bad in ({"ana": 0}, {"ana": 999}, {"ana": 60000}, {"ana": "20001"}, {"ana": True}):
        reply = host_door.handle({"op": "samba.reload", "args": {"changed": {"shares": []}, "numbers": bad}}, 0)
        assert reply["ok"] is False and "Kiboto's own range" in reply["error"], bad
    reply = host_door.handle(
        {"op": "samba.set_password", "args": {"name": "ana", "number": 0, "password": "x" * 12}}, 0
    )
    assert reply["ok"] is False
    assert host_door.handle(
        {"op": "samba.set_password", "args": {"name": "ana", "number": 20002, "password": "pw-1234567"}}, 0
    )["ok"]
    assert seen[-1] == 20002
    assert not any("pw-1234567" in line for line in audit.read_text().splitlines())  # passwords never in the audit


def test_the_door_points_samba_at_its_own_path_and_exports_only_storage(audit, monkeypatch, tmp_path):
    from backend import config
    from backend.services import nfs_engine, samba_host
    from backend.services.samba_engine import SAMBA_CONF_FILE

    pointed = []
    monkeypatch.setattr(samba_host, "point_samba_here", lambda conf: pointed.append(conf) or True)
    assert host_door.handle({"op": "samba.point_here", "args": {}}, 0)["ok"] and pointed == [SAMBA_CONF_FILE]
    store = tmp_path / "storage"
    (store / "photos").mkdir(parents=True)
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(store)])
    assert nfs_engine.exportable(str(store / "photos"))
    assert not nfs_engine.exportable("/etc") and not nfs_engine.exportable(str(tmp_path))
    eng = nfs_engine.NfsEngine.__new__(nfs_engine.NfsEngine)
    eng._exports = {
        "photos": nfs_engine.NfsExportRule(name="photos", path=str(store / "photos"), clients="192.168.1.0/24"),
        "etc": nfs_engine.NfsExportRule(name="etc", path="/etc", clients="*"),
    }
    full = eng.generate_exports_file_content()
    safe = eng.generate_exports_file_content(inside_storage_only=True)
    assert '"/etc"' in full and '"/etc"' not in safe and str(store / "photos") in safe


def test_samba_and_nfs_go_through_the_door_where_it_runs(monkeypatch):
    from backend.services import nfs_engine, samba_host

    calls = []
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, sorted(a))) or True)
    assert samba_host.reload({"shares": ["a"]}, {"ana": 20001}) is True
    assert samba_host.set_password("Ana", 20001, "secret-pw") is True
    assert samba_host.remove("ana") is True and samba_host.set_enabled("ana", False) is True
    assert samba_host.point_samba_here("/var/lib/kiboto/samba/smb.conf") is True
    eng = nfs_engine.NfsEngine.__new__(nfs_engine.NfsEngine)
    eng._exports = {}
    assert eng.apply_exports() is True
    assert [c[0] for c in calls] == [
        "samba.reload",
        "samba.set_password",
        "samba.remove",
        "samba.set_enabled",
        "samba.point_here",
        "nfs.apply",
    ]

    def refused(op, **a):
        raise door.DoorError("account numbers come from Kiboto's own range", "value")

    monkeypatch.setattr(door, "call", refused)
    assert samba_host.reload(None, {"ana": 5}) is False  # said in the log, answered as a failed run
    assert eng.apply_exports() is False


def test_snapshots_and_scrubs_go_through_the_door_where_it_runs(monkeypatch):
    from backend.hardware.pal.base import PlatformCapabilityError
    from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter

    adapter = GenericLinuxStorageAdapter.__new__(GenericLinuxStorageAdapter)
    calls = []
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, a)) or {"status": "done"})
    assert adapter.create_snapshot("tank", "media", "media_1", retention_days=7.0)["status"] == "done"
    assert adapter.delete_snapshot("tank", "media_1", reason=None)["status"] == "done"
    assert adapter.trigger_scrub("tank", "start")["status"] == "done"
    assert calls == [
        (
            "storage.create_snapshot",
            {
                "pool_id": "tank",
                "subvol_name": "media",
                "snapshot_name": "media_1",
                "readonly": True,
                "worm_mode": None,
                "retention_days": 7,
            },
        ),
        (
            "storage.delete_snapshot",
            {"pool_id": "tank", "snapshot_name": "media_1", "break_glass": False, "reason": ""},
        ),
        ("storage.scrub", {"pool_id": "tank", "action": "start"}),
    ]
    # the arguments the adapter sends are the ones the door takes
    for op, args in calls:
        host_door._checked({"op": op, "args": args})

    def locked(op, **a):
        raise door.DoorError("WORM compliance lock: this snapshot can't be deleted yet", "capability")

    monkeypatch.setattr(door, "call", locked)
    with pytest.raises(PlatformCapabilityError, match="WORM"):
        adapter.delete_snapshot("tank", "media_1")

    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: False)
    monkeypatch.setattr(adapter, "_trigger_scrub_here", lambda pool_id, action: {"here": pool_id})
    assert adapter.trigger_scrub("tank") == {"here": "tank"}


def test_the_door_runs_the_adapters_own_storage_code_for_a_pool_name_only(audit, monkeypatch):
    from backend.hardware import pal_storage
    from backend.hardware.pal.base import PlatformCapabilityError

    seen = []

    class Adapter:
        def trigger_scrub(self, pool_id, action):
            seen.append((pool_id, action))
            return {"status": "started"}

        def delete_snapshot(self, **kw):
            raise PlatformCapabilityError("WORM compliance lock")

    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: Adapter())
    reply = host_door.handle({"op": "storage.scrub", "args": {"pool_id": "tank", "action": "start"}}, 0)
    assert reply == {"ok": True, "result": {"status": "started"}} and seen == [("tank", "start")]
    for pool in ("", "/etc", "../x", "tank/../.."):
        reply = host_door.handle({"op": "storage.scrub", "args": {"pool_id": pool, "action": "start"}}, 0)
        assert reply["ok"] is False and reply["kind"] == "value", pool
    assert len(seen) == 1
    args = {"pool_id": "tank", "snapshot_name": "a", "break_glass": False, "reason": ""}
    reply = host_door.handle({"op": "storage.delete_snapshot", "args": args}, 0)
    assert reply["ok"] is False and reply["kind"] == "capability" and "WORM" in reply["error"]
    assert door.DoorError(reply["error"], reply["kind"]).as_error().kind == "capability"


def test_pools_go_through_the_door_where_it_runs(monkeypatch):
    from backend.hardware.pal.base import PoolUsedElsewhere
    from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter

    adapter = GenericLinuxStorageAdapter.__new__(GenericLinuxStorageAdapter)
    calls = []
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, a)) or {"status": "ok"})
    adapter.create_pool("tank", "zfs", "mirror", ("sdb", "sdc"), None)
    adapter.import_pool("old", force=1, guid=None)
    adapter.rename_pool("tank", "vault")
    adapter.export_pool("vault", force=0)
    adapter.destroy_pool("vault")
    adapter.erase_pool("vault")
    adapter.allow_changes("old")
    assert [c[0] for c in calls] == [
        "storage.create_pool",
        "storage.import_pool",
        "storage.rename_pool",
        "storage.export_pool",
        "storage.destroy_pool",
        "storage.erase_pool",
        "storage.allow_changes",
    ]
    assert calls[0][1]["disks"] == ["sdb", "sdc"] and calls[0][1]["mountpoint"] == ""
    assert calls[1][1] == {"pool_id": "old", "fs_type": "zfs", "target_mount": None, "force": True, "guid": ""}
    for op, args in calls:  # what the adapter sends is what the door takes
        host_door._checked({"op": op, "args": args})

    for kind, raised in (("used_elsewhere", PoolUsedElsewhere), ("lookup", LookupError)):

        def failing(op, kind=kind, **a):
            raise door.DoorError("old was last used by another system.", kind)

        monkeypatch.setattr(door, "call", failing)
        with pytest.raises(raised):
            adapter.import_pool("old")


def test_the_door_checks_a_new_pool_as_the_page_does(audit, monkeypatch, tmp_path):
    from backend import config
    from backend.hardware import disk_safety, pal_storage

    made = []

    class Adapter:
        def _resolve_disk_path(self, d):
            return "/dev/" + d

        def create_pool(self, **kw):
            made.append(kw)
            return {"status": "provisioned"}

        def import_pool(self, **kw):
            made.append(kw)
            return {"status": "imported"}

        def rename_pool(self, **kw):
            made.append(kw)
            return {"status": "renamed"}

    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: Adapter())
    monkeypatch.setattr(config, "POOL_PATH", str(tmp_path))
    in_use = {"/dev/sda": "in use: sda1 is mounted at /"}
    seen = []

    def check(disks, allow_erase=False):
        seen.append(allow_erase)
        return [{"disk": d, "reason": in_use[d]} for d in disks if d in in_use]

    monkeypatch.setattr(disk_safety, "check_disks", check)
    good = {"name": "tank", "fs_type": "btrfs", "profile": "raid1", "disks": ["sdb", "sdc"], "mountpoint": ""}

    def create(**changes):
        return host_door.handle({"op": "storage.create_pool", "args": {**good, **changes}}, 0)

    assert create()["ok"] is True and made[-1]["disks"] == ["sdb", "sdc"] and seen == [True]
    assert create(mountpoint=str(tmp_path / "tank"))["ok"] is True
    assert made[-1]["mountpoint"] == os.path.realpath(tmp_path / "tank")
    for changes, why in (
        ({"disks": ["sda"]}, "can't be formatted"),
        ({"disks": []}, "one to 64"),
        ({"disks": [7]}, "one to 64"),
        ({"name": "-x"}, "Pool name"),
        ({"fs_type": "ntfs"}, "Kiboto makes"),
        ({"profile": "raid1 -f"}, "Kiboto makes"),
        ({"mountpoint": "/etc"}, "must be inside"),
    ):
        reply = create(**changes)
        assert reply["ok"] is False and why in reply["error"], (changes, reply)
    assert len(made) == 2

    def imp(**changes):
        args = {"pool_id": "old", "fs_type": "zfs", "target_mount": None, "force": False, "guid": "123", **changes}
        return host_door.handle({"op": "storage.import_pool", "args": args}, 0)

    assert imp()["ok"] is True and imp(target_mount="/mnt/old")["ok"] is True
    for changes in ({"target_mount": "/etc"}, {"pool_id": "-o"}, {"guid": "x"}, {"fs_type": "Z FS"}):
        assert imp(**changes)["ok"] is False, changes
    reply = host_door.handle({"op": "storage.rename_pool", "args": {"pool_id": "tank", "new_name": "../x"}}, 0)
    assert reply["ok"] is False
    assert host_door.handle({"op": "storage.rename_pool", "args": {"pool_id": "tank", "new_name": "vault"}}, 0)["ok"]


def test_a_request_the_door_got_is_not_run_again_here(monkeypatch):
    timeouts = []

    class Sock:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, t):
            timeouts.append(t)

        def connect(self, p):
            pass

        def sendall(self, b):
            pass

        def recv(self, n):
            raise TimeoutError("timed out")

    monkeypatch.setattr(door.socket, "socket", Sock)
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    here = []
    with pytest.raises(RuntimeError, match="did not finish"):
        door.via("storage.create_pool", lambda **a: here.append(a), name="tank")
    assert here == [] and timeouts == [door.LONG["storage.create_pool"]]
    with pytest.raises(door.DoorError):
        door.call("door.ping")
    assert timeouts[-1] == 120


def test_pool_rules():
    from backend.hardware.pal import pool_rules

    assert pool_rules.pool_id("tank/media") == "tank/media"
    for bad in ("", "/mnt/x", "a/../b", "-o"):
        with pytest.raises(ValueError):
            pool_rules.pool_id(bad)
    assert pool_rules.import_mount("") is None and pool_rules.new_pool_mount(" ") == ""
    with pytest.raises(ValueError):
        pool_rules.import_mount("relative/x")


def test_a_shared_folders_folder_and_limit_go_through_the_door(audit, monkeypatch, tmp_path):
    from backend.hardware import pal_storage
    from backend.hardware.pal import generic_linux
    from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter
    from backend.services import samba_engine

    adapter = GenericLinuxStorageAdapter.__new__(GenericLinuxStorageAdapter)
    calls = []
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, a)) or {"made": "subvolume", "quota": None})
    assert adapter.make_share_folder("/mnt/tank/media", 5 * 1024**3)["made"] == "subvolume"
    assert calls == [("storage.share_folder", {"path": "/mnt/tank/media", "quota_bytes": 5 * 1024**3})]
    host_door._checked({"op": calls[0][0], "args": calls[0][1]})

    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: False)
    monkeypatch.setattr(adapter, "_make_share_dir", lambda p: "folder")
    monkeypatch.setattr(generic_linux.fs_quota, "apply", lambda p, n: {"enforced": True, "bytes": n})
    assert adapter.make_share_folder(str(tmp_path / "a")) == {"made": "folder", "quota": None}
    assert adapter.make_share_folder(str(tmp_path / "a"), 10)["quota"] == {"enforced": True, "bytes": 10}

    made = []

    class Adapter:
        @staticmethod
        def _not_on_the_system_disk(p):
            if p.endswith("/boot-disk"):
                raise ValueError("on the system disk")
            return p

        def make_share_folder(self, **kw):
            made.append(kw)
            return {"made": "folder", "quota": None}

    def inside(p):
        if not p.startswith(str(tmp_path) + "/"):
            raise ValueError("Share path must be inside the storage pool")
        return p

    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: Adapter())
    monkeypatch.setattr(samba_engine, "validate_share_path", inside)

    def folder(path, quota=0):
        return host_door.handle({"op": "storage.share_folder", "args": {"path": path, "quota_bytes": quota}}, 0)

    assert folder(str(tmp_path / "media"), 1024)["ok"] is True and made[-1]["quota_bytes"] == 1024
    for args in (("/etc",), (str(tmp_path / "boot-disk"),), (str(tmp_path / "x"), -1)):
        assert folder(*args)["ok"] is False, args
    assert len(made) == 1


def test_self_tests_and_drive_sleep_go_through_the_door(audit, monkeypatch):
    import subprocess

    from backend.hardware import disks, drive_sleep

    calls = []
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(
        door,
        "call",
        lambda op, **a: calls.append((op, a)) or ([0, "testing has begun", ""] if op.startswith("smart") else []),
    )
    assert disks.self_test("sdb", "short") == (0, "testing has begun", "")
    assert drive_sleep.apply(20) == []
    assert calls == [
        ("smart.self_test", {"dev_name": "sdb", "action": "short"}),
        ("drives.sleep_after", {"minutes": 20}),
    ]
    for op, args in calls:
        host_door._checked({"op": op, "args": args})

    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: False)
    ran = []
    monkeypatch.setattr(disks, "_get_smart_device_type", lambda name, nvme: "sat")
    monkeypatch.setattr(
        disks.subprocess, "run", lambda cmd, **kw: ran.append(cmd) or subprocess.CompletedProcess(cmd, 4, "x", "busy")
    )
    code, out, err = disks.self_test("sdb", "abort")
    assert code == 4 and err == "busy" and "busy" in out and ran[0][:2] == ["smartctl", "-X"]
    with pytest.raises(ValueError):
        disks.self_test("sdb", "-d")


def test_the_door_starts_a_self_test_only_on_a_drive(audit, monkeypatch, tmp_path):
    from backend.hardware import disks

    started = []
    monkeypatch.setattr(disks, "self_test", lambda name, action: started.append(name) or (0, "", ""))
    monkeypatch.setattr(
        disks, "_resolve_dev_path", lambda name: "/dev/null" if name == "notblk" else str(tmp_path / name)
    )

    def test(name):
        return host_door.handle({"op": "smart.self_test", "args": {"dev_name": name, "action": "short"}}, 0)

    for name in ("../sda", "-x", "/dev/sda", "notblk", "gone"):
        assert test(name)["ok"] is False, name
    assert started == []
    monkeypatch.setattr(host_door.os, "stat", lambda p: os.stat_result((0o060660,) + (0,) * 9))
    assert test("sdb")["ok"] is True and started == ["sdb"]


def test_updates_and_packages_go_through_the_door(monkeypatch):
    from backend.services import host_set, native_update

    calls = []
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, a)) or "/opt/kiboto/releases/x")
    assert native_update.start("ghcr.io/fr0styx/kiboto:2.0.7", "2.0.7", "/elsewhere", 1) == "/opt/kiboto/releases/x"
    native_update.start_back("snap-1", "/elsewhere", 1)
    native_update.add_missing_tools_now()
    assert host_set.check() is True and host_set.start() is True
    assert calls == [
        ("update.start", {"image": "ghcr.io/fr0styx/kiboto:2.0.7", "version": "2.0.7"}),
        ("update.back", {"snapshot_id": "snap-1"}),
        ("packages.add_missing", {}),
        ("packages.check", {}),
        ("packages.host_set", {}),
    ]
    for op, args in calls:
        host_door._checked({"op": op, "args": args})

    def refused(op, **a):
        raise door.DoorError("Not updating: the image's signature could not be verified (no signature).", "value")

    monkeypatch.setattr(door, "call", refused)
    with pytest.raises(native_update.UpdateFailed, match="signature"):
        native_update.start("ghcr.io/fr0styx/kiboto:2.0.7", "2.0.7", "/elsewhere", 1)
    with pytest.raises(native_update.UpdateFailed):
        native_update.start_back("snap-1", "/elsewhere", 1)

    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: False)
    here = []
    monkeypatch.setattr(native_update, "_start_here", lambda *a, **k: here.append(a) or "rel")
    assert native_update.start("img", "v", "/data", 8082) == "rel" and here == [("img", "v", "/data", 8082)]


def test_the_door_checks_the_image_before_it_installs_it(audit, monkeypatch):
    from backend import config
    from backend.services import host_set, image_signature, native_update

    started, checked = [], []
    monkeypatch.setattr(image_signature, "install_allowed", lambda image: checked.append(image) or "sha256:" + "a" * 64)
    monkeypatch.setattr(native_update, "start", lambda *a: started.append(a) or "rel")
    monkeypatch.setattr(native_update, "start_back", lambda *a: started.append(a))
    monkeypatch.setattr(native_update, "add_missing_tools", lambda rel: [rel])
    monkeypatch.setattr(host_set, "check", lambda: True)
    monkeypatch.setattr(host_set, "start", lambda: False)

    def op(name, **args):
        return host_door.handle({"op": name, "args": args}, 0)

    assert op("update.start", image="ghcr.io/fr0styx/kiboto:2.0.7", version="2.0.7")["result"] == "rel"
    assert started == [("ghcr.io/fr0styx/kiboto:2.0.7", "2.0.7", config.DATA_DIR, config.PORT)]
    assert op("update.start", image="x", version="-rf /")["ok"] is False and len(checked) == 1
    assert op("update.back", snapshot_id="../x")["ok"] is False
    assert op("update.back", snapshot_id="snap-1")["ok"] is True and started[-1][0] == "snap-1"
    assert op("packages.add_missing")["result"] == [os.path.join(native_update.PREFIX, "current")]
    assert op("packages.check")["result"] is True and op("packages.host_set")["result"] is False


def test_install_allowed(monkeypatch):
    from backend import config
    from backend.services import docker_client, image_signature

    good = "sha256:" + "b" * 64
    seen = {}
    monkeypatch.setattr(
        docker_client,
        "request",
        lambda m, path, *a, **k: (
            200,
            {"RepoDigests": [f"ghcr.io/fr0styx/kiboto@{good}", "other/x@sha256:" + "c" * 64]},
        ),
    )
    monkeypatch.setattr(config, "UPDATE_SIGNATURES", "enforce")
    monkeypatch.setattr(
        image_signature,
        "verify_image",
        lambda d, tags: seen.setdefault("v", (d, tags)) and image_signature.SignatureResult(True, "ok", "ci"),
    )
    assert image_signature.install_allowed("ghcr.io/fr0styx/kiboto:2.0.7") == good and seen["v"][0] == good
    for bad in ("../../containers/json", "UPPER", "ghcr.io/fr0styx/kiboto@sha256:" + "c" * 64):
        with pytest.raises(ValueError):
            image_signature.install_allowed(bad)
    monkeypatch.setattr(
        image_signature, "verify_image", lambda d, tags: image_signature.SignatureResult(False, "no sig")
    )
    with pytest.raises(ValueError, match="no sig"):
        image_signature.install_allowed("ghcr.io/fr0styx/kiboto:2.0.7")
    monkeypatch.setattr(config, "UPDATE_SIGNATURES", "warn")  # the machine's own setting, not the caller's
    assert image_signature.install_allowed("ghcr.io/fr0styx/kiboto:2.0.7") == good
    monkeypatch.setattr(docker_client, "request", lambda *a, **k: (404, None))
    with pytest.raises(ValueError, match="downloaded"):
        image_signature.install_allowed("ghcr.io/fr0styx/kiboto:2.0.7")


def test_the_data_key_is_opened_and_sealed_by_the_door_where_it_runs(monkeypatch):
    from backend import machine_key, runtime

    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    monkeypatch.setattr(machine_key, "_cache", {})
    monkeypatch.setattr(machine_key, "_refused_until", [0.0])
    answers = {
        "keys.text": "k" * 64,
        "keys.wanted": True,
        "keys.ensure": "sealed",
        "keys.status": {"managed": True, "on": True},
        "keys.to_write_down": "",
        "keys.written_down": False,
        "keys.unlock": "chip",
        "keys.adopt": "chip",
        "keys.renew": True,
    }
    calls = []
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, sorted(a))) or answers[op])
    assert machine_key.key_text() == "k" * 64 and machine_key.key_text() == "k" * 64  # the second from memory
    assert machine_key.wanted() is True and machine_key.ensure() == "sealed"
    assert machine_key.status()["on"] is True and machine_key.recovery_key_to_write_down() == ""
    assert machine_key.written_down() is False and machine_key.renew_recovery_key() is True
    assert machine_key.unlock("ABCD-EFGH") == "chip" and machine_key._cache == {}  # sealed again: asked anew
    assert machine_key.adopt("a" * 64, {"v": 1}) == "chip"
    assert [c[0] for c in calls] == [
        "keys.text",
        "keys.wanted",
        "keys.ensure",
        "keys.status",
        "keys.to_write_down",
        "keys.written_down",
        "keys.renew",
        "keys.unlock",
        "keys.adopt",
    ]
    assert calls[-2:] == [("keys.unlock", ["typed"]), ("keys.adopt", ["box", "data_key"])]

    def locked(op, **a):
        raise door.DoorError(machine_key.LOCKED, "runtime")

    monkeypatch.setattr(door, "call", locked)
    with pytest.raises(machine_key.MachineKeyError, match="could not open"):
        machine_key.key_text()
    with pytest.raises(machine_key.MachineKeyError):
        machine_key.key_text()  # not asked again at once
    assert machine_key._refused_until[0] > 0


def test_the_door_keeps_the_key_to_a_machine_kiboto_runs(audit, monkeypatch):
    from backend import machine_key, runtime

    monkeypatch.setattr(machine_key, "unlock", lambda typed: "disk" if typed else "")
    monkeypatch.setattr(runtime, "managed_host", lambda: False)
    reply = host_door.handle({"op": "keys.unlock", "args": {"typed": "ABCD"}}, 0)
    assert reply["ok"] is False and "no data key" in reply["error"]
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    assert host_door.handle({"op": "keys.unlock", "args": {"typed": "ABCD"}}, 0) == {"ok": True, "result": "disk"}
    assert all("ABCD" not in line for line in audit.read_text().splitlines())  # never an argument in the log


def test_kiboto_waits_for_the_door_it_restarted(monkeypatch, tmp_path):
    from backend import main
    from backend.services import native_update

    monkeypatch.setattr(native_update, "ensure_units", lambda rel, **k: [])
    monkeypatch.setattr(native_update, "UNIT_DIR", str(tmp_path))
    waited = []
    monkeypatch.setattr(door, "wait_open", lambda: waited.append(1) or False)
    main._door_of_this_version()
    assert waited == []  # no door on this machine
    (tmp_path / "kiboto-door.service").write_text("[Unit]\n")
    main._door_of_this_version()
    assert waited == [1]


def test_wait_open_asks_until_the_door_answers(monkeypatch):
    answers = [OSError("no socket yet"), door.DoorError("starting"), "pong"]

    def call(op, **kw):
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    monkeypatch.setattr(door, "call", call)
    monkeypatch.setattr(door.time, "sleep", lambda s: None)
    assert door.wait_open(timeout=5) is True and answers == []
    monkeypatch.setattr(door, "call", lambda op, **kw: (_ for _ in ()).throw(OSError("gone")))
    assert door.wait_open(timeout=0) is False


def test_the_door_is_restarted_before_the_data_key_asks_it():
    import inspect

    from backend import main

    src = inspect.getsource(main.startup_system)
    assert "_door_first()" in src
    assert src.index("_door_first()") < src.index("_make_machine_key()")
    assert "_door_of_this_version()" not in inspect.getsource(main._start_app_names)


def test_door_first_only_where_kiboto_runs_the_machine(monkeypatch):
    from backend import main, runtime

    done = []
    monkeypatch.setattr(main, "_door_of_this_version", lambda: done.append(1))
    monkeypatch.setattr(runtime, "managed_host", lambda: False)
    main._door_first()
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    main._door_first()
    assert done == [1]


def test_fans_go_through_the_door_where_it_runs(monkeypatch):
    from backend.hardware import fans

    calls = []
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, a)) or True)
    assert fans._write_sysfs("/sys/class/hwmon/hwmon2/pwm1", "120") is True
    mmio = fans.ZettlabMmioFanController.__new__(fans.ZettlabMmioFanController)
    assert mmio.write_pwm(2, 90) is True
    assert calls[0] == ("fans.sysfs", {"path": "/sys/class/hwmon/hwmon2/pwm1", "value": 120})
    assert calls[1] == ("fans.ec_pwm", {"channel": 2, "pwm_val": 90})
    for op, args in calls:
        host_door._checked({"op": op, "args": args})

    def refused(op, **a):
        raise door.DoorError("only a fan's pwm file", "value")

    monkeypatch.setattr(door, "call", refused)
    assert fans._write_sysfs("/sys/class/hwmon/hwmon2/pwm1", 1) is False
    assert mmio.write_pwm(1, 50) is False


def test_the_door_writes_only_fan_files(audit, monkeypatch):
    from backend import config
    from backend.hardware import fans

    written = []
    monkeypatch.setattr(config, "HOST_SYS", "/sys")
    monkeypatch.setattr(fans, "_write_sysfs", lambda path, value: written.append((path, value)) or True)

    def fan(path, value=100):
        return host_door.handle({"op": "fans.sysfs", "args": {"path": path, "value": value}}, 0)

    assert fan("/sys/class/hwmon/hwmon3/pwm2")["ok"] and fan("/sys/class/hwmon/hwmon3/pwm2_enable", 1)["ok"]
    for bad in (
        "/sys/power/state",
        "/sys/class/hwmon/hwmon3/../../../power/state",
        "/etc/passwd",
        "/sys/class/hwmon/hwmon3/temp1_max",
    ):
        assert fan(bad)["ok"] is False, bad
    assert fan("/sys/class/hwmon/hwmon3/pwm2", 999)["ok"] is False
    assert len(written) == 2

    monkeypatch.setattr(fans, "get_mmio_fan_controller", lambda: None)
    reply = host_door.handle({"op": "fans.ec_pwm", "args": {"channel": 1, "pwm_val": 10}}, 0)
    assert reply["ok"] is False and "no such fan controller" in reply["error"]
    assert host_door.handle({"op": "fans.ec_pwm", "args": {"channel": 9, "pwm_val": 10}}, 0)["ok"] is False


def test_kiboto_uses_the_doors_docker_proxy(monkeypatch, tmp_path):
    from backend import main, runtime
    from backend.services import native_update

    sock = tmp_path / "docker.sock"
    monkeypatch.setattr(door, "DOCKER_SOCK", str(sock))
    monkeypatch.setattr(native_update, "UNIT_DIR", str(tmp_path))
    monkeypatch.delenv("KIBOTO_DOCKER_SOCK", raising=False)
    monkeypatch.setattr(runtime, "managed_host", lambda: False)
    assert main._proxy_of_the_door(wait=0) is False
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    assert main._proxy_of_the_door(wait=0) is False  # no door here
    (tmp_path / "kiboto-door.service").write_text("[Unit]\n")
    assert main._proxy_of_the_door(wait=0) is False  # the door's proxy is not up
    sock.write_text("")
    assert main._proxy_of_the_door(wait=0) is True
    assert os.environ["KIBOTO_DOCKER_SOCK"] == str(sock)


def test_the_door_keeps_the_docker_proxy_running(monkeypatch, tmp_path):
    import subprocess

    from backend import config

    runs = []

    class Proc:
        def __init__(self, cmd, env):
            runs.append((cmd, env))

        def wait(self):
            return 1

    monkeypatch.setattr(subprocess, "Popen", Proc)
    monkeypatch.setattr(host_door, "_give_to_web_group", lambda path: True)
    monkeypatch.setattr(host_door.time, "sleep", lambda s: None)
    host_door.keep_docker_proxy(str(tmp_path / "d.sock"), rounds=2)
    assert len(runs) == 2 and runs[0][0][-1] == "backend.docker_proxy"
    assert runs[0][1]["KIBOTO_DOCKER_PROXY_SOCK"] == str(tmp_path / "d.sock")

    started, served = [], []
    raw = tmp_path / "docker-raw.sock"
    raw.write_text("")
    monkeypatch.setattr(config, "RAW_DOCKER_SOCK", str(raw))
    monkeypatch.setattr(host_door, "keep_docker_proxy", lambda: started.append(1))
    monkeypatch.setattr(host_door, "serve", lambda: served.append(1))
    monkeypatch.delenv(door.IN_DOOR, raising=False)

    class Now:  # the thread's work, done at once
        def __init__(self, target, name, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(host_door.threading, "Thread", Now)
    assert host_door.main() == 0
    assert started == [1] and served == [1]


def test_the_proxy_socket_goes_to_the_web_users_group(monkeypatch, tmp_path):
    import types

    owned = []
    sock = tmp_path / "s"
    groups = {"kiboto": types.SimpleNamespace(gr_gid=4242)}

    def getgrnam(name):
        return groups[name]  # KeyError for a group that is not there, as grp does

    monkeypatch.setattr(host_door.grp, "getgrnam", getgrnam)
    monkeypatch.setattr(host_door.os, "chown", lambda p, u, g: owned.append((p, u, g)))
    assert host_door._give_to_web_group(str(sock), wait=0) is False  # not there yet
    sock.write_text("")
    monkeypatch.setattr(host_door, "USER", "nobody-here")
    assert host_door._give_to_web_group(str(sock), wait=0) is False and owned == []
    monkeypatch.setattr(host_door, "USER", "kiboto")
    assert host_door._give_to_web_group(str(sock), wait=0) is True
    assert owned == [(str(sock), -1, 4242)]


def test_files_are_handed_over_by_the_door_once_kiboto_is_not_root(monkeypatch):
    from backend import owned

    calls = []
    monkeypatch.setattr(owned, "_me", lambda: 1000)
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(
        door,
        "call",
        lambda op, **a: calls.append((op, a)) or ({"seen": 2, "given": 1} if op == "files.give_back" else True),
    )
    before = os.stat_result((0o100644, 0, 0, 1, 20001, 100, 0, 0, 0, 0))
    assert owned.like_folder("/mnt/storage/tank/a/b.txt") is True
    owned.rights_again("/mnt/storage/tank/a")
    assert owned.to_people("/mnt/storage/tank/a") is True
    assert owned.to_person("/mnt/storage/tank/homes/ana", 20001) is True
    owned.like_source("/mnt/storage/tank/a/x", "/mnt/storage/tank/b/x")
    owned.like_before("/mnt/storage/tank/a/b.txt", before)
    assert owned.give_back("/mnt/storage/tank/a") == {"seen": 2, "given": 1}
    assert [c[0] for c in calls] == [
        "files.like_folder",
        "files.rights_again",
        "files.to_people",
        "files.to_person",
        "files.like_source",
        "files.hand_back",
        "files.give_back",
    ]
    assert calls[5][1] == {"path": "/mnt/storage/tank/a/b.txt", "uid": 20001, "gid": 100}
    for op, args in calls:
        host_door._checked({"op": op, "args": args})

    def gone(op, **a):
        raise FileNotFoundError("no door")

    monkeypatch.setattr(door, "call", gone)
    assert owned.like_folder("/mnt/storage/tank/a/b.txt") is False
    assert owned.give_back("/mnt/storage/tank/a") == {"seen": 0, "given": 0}


def test_the_door_hands_files_over_only_in_the_storage_folders(audit, monkeypatch, tmp_path):
    from backend import config, owned
    from backend.services import smb_accounts

    store = tmp_path / "storage"
    (store / "a").mkdir(parents=True)
    monkeypatch.setattr(config, "POOL_PATH", str(store))
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [])
    done = []
    for name in ("like_folder", "rights_again", "like_source", "to_people", "to_person", "_hand"):
        monkeypatch.setattr(owned, name, lambda *a, name=name, **k: done.append(name) or True)
    monkeypatch.setattr(owned, "give_back", lambda top, keep_out: done.append("give_back") or {"seen": 0, "given": 0})

    def op(name, **args):
        return host_door.handle({"op": f"files.{name}", "args": args}, 0)

    inside, folder = str(store / "a" / "f.txt"), str(store / "a")
    assert op("like_folder", path=inside)["ok"] and op("rights_again", path=inside)["ok"]
    assert op("like_source", src=inside, dst=str(store / "a" / "g.txt"))["ok"]
    assert op("give_back", top=folder)["result"] == {"seen": 0, "given": 0}
    assert op("to_people", folder=folder, user="nobody", group="users", mode=0o775)["ok"]
    assert op("to_person", folder=folder, uid=smb_accounts.FIRST_UID, gid=100, mode=0o700)["ok"]
    assert op("hand_back", path=inside, uid=20001, gid=100)["ok"]
    for name, args in (
        ("like_folder", {"path": "/etc/passwd"}),
        ("like_folder", {"path": "relative/x"}),
        ("like_source", {"src": "/etc/shadow", "dst": inside}),
        ("give_back", {"top": "/etc"}),
        ("to_people", {"folder": folder, "user": "root", "group": "root", "mode": 0o775}),
        ("to_people", {"folder": folder, "user": "nobody", "group": "users", "mode": 0o4775}),
        ("to_person", {"folder": folder, "uid": 0, "gid": 100, "mode": 0o700}),
        ("to_person", {"folder": folder, "uid": smb_accounts.FIRST_UID, "gid": 0, "mode": 0o700}),
        ("hand_back", {"path": inside, "uid": 0, "gid": 100}),
    ):
        assert op(name, **args)["ok"] is False, (name, args)
    assert done == ["like_folder", "rights_again", "like_source", "give_back", "to_people", "to_person", "_hand"]


def test_what_the_web_user_made_counts_as_kibotos(monkeypatch):
    import types

    from backend import owned

    monkeypatch.setattr(owned.pwd, "getpwnam", lambda n: types.SimpleNamespace(pw_uid=999))
    assert owned._ours() == {os.geteuid(), 999}

    def missing(n):
        raise KeyError(n)

    monkeypatch.setattr(owned.pwd, "getpwnam", missing)
    assert owned._ours() == {os.geteuid()}


def test_the_apps_names_are_written_by_the_door(audit, monkeypatch):
    from backend import runtime
    from backend.services import app_hosts

    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    calls = []
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, a)) or True)
    assert app_hosts.sync() is True and calls == [("hosts.apps", {})]

    def refused(op, **a):
        raise door.DoorError("no", "runtime")

    monkeypatch.setattr(door, "call", refused)
    assert app_hosts.sync() is False

    synced = []
    monkeypatch.setattr(app_hosts, "sync", lambda: synced.append(1) or True)
    assert host_door.handle({"op": "hosts.apps", "args": {}}, 0) == {"ok": True, "result": True} and synced == [1]


def test_a_machine_on_a_bridge_gets_a_tap_from_the_door(monkeypatch):
    from backend.services import vm_qemu

    calls = []
    monkeypatch.setattr(vm_qemu.os, "geteuid", lambda: 999)
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, a)) or True)
    name = vm_qemu.tap_name("vm-1")
    assert name.startswith("kbt") and len(name) == 11 and vm_qemu._door_tap("vm-1", "br0") == name
    vm_qemu._door_tap_gone("vm-1")
    assert calls == [("vm.tap", {"name": name, "bridge": "br0"}), ("vm.tap_remove", {"name": name})]
    for op, args in calls:
        host_door._checked({"op": op, "args": args})

    def refused(op, **a):
        raise door.DoorError("br0 is not a bridge here", "value")

    monkeypatch.setattr(door, "call", refused)
    assert vm_qemu._door_tap("vm-1", "br0") == ""
    vm_qemu._door_tap_gone("vm-1")  # said in the log only
    monkeypatch.setattr(vm_qemu.os, "geteuid", lambda: 0)
    assert vm_qemu._door_tap("vm-1", "br0") == ""  # as root qemu-bridge-helper does it


def test_the_door_makes_only_a_machines_tap_on_a_bridge(audit, monkeypatch):
    import subprocess

    from backend import proc

    ran = []
    monkeypatch.setattr(
        proc, "run_bounded", lambda cmd, **kw: ran.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")
    )
    there = {"/sys/class/net/br0/bridge"}
    monkeypatch.setattr(host_door.os.path, "isdir", lambda p: p in there)
    monkeypatch.setattr(host_door.os.path, "exists", lambda p: False)

    def op(which, **args):
        return host_door.handle({"op": which, "args": args}, 0)

    assert op("vm.tap", name="kbt0123abcd", bridge="br0")["ok"]
    assert ran[0] == ["ip", "tuntap", "add", "dev", "kbt0123abcd", "mode", "tap", "user", host_door.USER]
    assert ran[1][-2:] == ["master", "br0"] and ran[2][-1] == "up"
    for name, bridge in (("eth0", "br0"), ("kbt0123abcd", "eth0"), ("kbt0123abcd", "br0; reboot")):
        assert op("vm.tap", name=name, bridge=bridge)["ok"] is False
    assert op("vm.tap_remove", name="eth0")["ok"] is False
    assert op("vm.tap_remove", name="kbt0123abcd")["ok"] and len(ran) == 3  # not there: nothing to remove
    monkeypatch.setattr(
        proc, "run_bounded", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, "", "RTNETLINK: busy")
    )
    reply = op("vm.tap", name="kbt0123abcd", bridge="br0")
    assert reply["ok"] is False and "busy" in reply["error"]


def test_the_name_service_is_started_by_the_door(audit, monkeypatch):
    from backend import runtime
    from backend.services import nas_name

    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    calls = []
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, a)) or {"running": True})
    assert nas_name.ensure() == {"running": True} and calls == [("names.ensure", {})]
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: False)
    monkeypatch.setattr(nas_name, "config", lambda: {"enabled": False, "held": False})
    monkeypatch.setattr(nas_name, "_ensure_service", lambda cfg: {"here": cfg["enabled"]})
    assert nas_name.ensure() == {"here": False}
    ensured = []
    monkeypatch.setattr(nas_name, "ensure", lambda: ensured.append(1) or {"running": False})
    assert host_door.handle({"op": "names.ensure", "args": {}}, 0)["result"] == {"running": False} and ensured == [1]


def test_restart_and_shut_down_go_through_the_door(audit, monkeypatch):
    from backend.services import host_power

    monkeypatch.setattr(host_power, "test_mode", lambda: False)
    calls = []
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(
        door, "call", lambda op, **a: calls.append((op, a)) or {"started": True, "how": "/sbin/reboot", "error": ""}
    )
    assert host_power.run("reboot")["started"] and calls == [("power.run", {"action": "reboot"})]
    host_door._checked({"op": "power.run", "args": {"action": "reboot"}})

    def gone_down(op, **a):
        raise door.DoorError("the door did not finish answering (ConnectionResetError)", "runtime")

    monkeypatch.setattr(door, "call", gone_down)
    assert host_power.run("shutdown") == {"started": True, "how": "door", "error": ""}

    def failed(op, **a):
        raise door.DoorError("/sbin/poweroff failed (exit 1)", "runtime")

    monkeypatch.setattr(door, "call", failed)
    assert host_power.run("shutdown")["started"] is False

    def no_door(op, **a):
        raise FileNotFoundError("no socket")

    monkeypatch.setattr(door, "call", no_door)
    monkeypatch.setattr(
        host_power, "_run_here", lambda action, cmds=None: {"started": False, "how": "", "error": "here"}
    )
    assert host_power.run("shutdown")["error"] == "here"

    ran = []
    monkeypatch.setattr(host_power, "run", lambda action, cmds=None: ran.append(action) or {"started": True})
    assert host_door.handle({"op": "power.run", "args": {"action": "shutdown"}}, 0)["ok"] and ran == ["shutdown"]
    assert host_door.handle({"op": "power.run", "args": {"action": "halt -f"}}, 0)["ok"] is False


def test_usb_disks_are_opened_and_ejected_by_the_door(audit, monkeypatch):
    from backend.hardware import usb_mount

    calls = []
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, a)) or "/mnt/disks/STICK")
    assert usb_mount.open_disk("/dev/sdb1") == "/mnt/disks/STICK"
    usb_mount.eject("/mnt/disks/STICK")
    assert calls == [("usb.open", {"device": "/dev/sdb1"}), ("usb.eject", {"path": "/mnt/disks/STICK"})]
    for op, args in calls:
        host_door._checked({"op": op, "args": args})

    def refused(op, **a):
        raise door.DoorError("That is not a USB disk Kiboto can open here.", "value")

    monkeypatch.setattr(door, "call", refused)
    with pytest.raises(ValueError, match="not a USB disk"):
        usb_mount.open_disk("/dev/sda")

    opened = []
    monkeypatch.setattr(usb_mount, "open_disk", lambda device: opened.append(device) or "/mnt/disks/x")
    monkeypatch.setattr(usb_mount, "eject", lambda path: opened.append(path))
    assert host_door.handle({"op": "usb.open", "args": {"device": "/dev/sdb1"}}, 0)["result"] == "/mnt/disks/x"
    assert host_door.handle({"op": "usb.eject", "args": {"path": "/mnt/disks/x"}}, 0)["ok"]
    assert opened == ["/dev/sdb1", "/mnt/disks/x"]


def test_a_home_and_its_limit_are_made_by_the_door(audit, monkeypatch):
    from backend.services import user_spaces

    calls, noted = [], []
    monkeypatch.setattr(user_spaces.os, "geteuid", lambda: 999)
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(
        door,
        "call",
        lambda op, **a: (
            calls.append((op, a))
            or {"home": "/mnt/storage/tank/homes/ana", "subvolume": True, "quota": {"enforced": True, "reason": ""}}
        ),
    )
    monkeypatch.setattr(user_spaces, "_record", lambda home, result: noted.append((home, result["quota_bytes"])))
    got = user_spaces.ensure_home("ana", 10)
    assert got == {"home": "/mnt/storage/tank/homes/ana", "subvolume": True, "fs_quota": True}
    monkeypatch.setattr(user_spaces, "home_of", lambda u: "/")  # a folder that is there
    assert user_spaces.set_quota("ana", 20) is True
    assert calls == [
        ("files.home", {"username": "ana", "quota_bytes": 10, "only_limit": False}),
        ("files.home", {"username": "ana", "quota_bytes": 20, "only_limit": True}),
    ]
    assert noted == [("/mnt/storage/tank/homes/ana", 10), ("/mnt/storage/tank/homes/ana", 20)]  # recorded here
    for op, args in calls:
        host_door._checked({"op": op, "args": args})


def test_the_door_makes_a_home_only_for_someone_who_is_there(audit, monkeypatch):
    from backend import users_db
    from backend.services import user_spaces

    monkeypatch.setattr(users_db, "get_user_by_username", lambda u: {"username": u} if u == "ana" else None)
    monkeypatch.setattr(user_spaces, "make_home", lambda u: (f"/homes/{u}", True))
    monkeypatch.setattr(user_spaces, "home_of", lambda u: f"/homes/{u}")
    monkeypatch.setattr(user_spaces.fs_quota, "apply", lambda home, n: {"enforced": n > 0, "reason": ""})

    def home(username, quota=0, only=False):
        return host_door.handle(
            {"op": "files.home", "args": {"username": username, "quota_bytes": quota, "only_limit": only}}, 0
        )

    assert home("ana")["result"] == {"home": "/homes/ana", "subvolume": True, "quota": None}
    assert home("ana", 5)["result"]["quota"] == {"enforced": True, "reason": ""}
    assert home("ana", 0, True)["result"] == {
        "home": "/homes/ana",
        "subvolume": False,
        "quota": {"enforced": False, "reason": ""},
    }
    for bad in ("bob", "../root", ""):
        assert home(bad)["ok"] is False, bad
    assert home("ana", -1)["ok"] is False


def test_encrypted_folders_are_mounted_by_the_door_once_kiboto_is_not_root(audit, monkeypatch):
    from backend.services import encrypted_folders as ef

    calls = []
    monkeypatch.setattr(ef.os, "geteuid", lambda: 999)
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, sorted(a))) or True)
    ef._mount("/mnt/storage/tank/photos/.enc/fam", "/mnt/encrypted/fam", "a long pass phrase", read_only=True)
    assert ef._unmount("/mnt/encrypted/fam") is True
    assert calls == [("crypt.mount", ["cipher", "password", "plain", "read_only"]), ("crypt.unmount", ["path"])]

    def wrong(op, **a):
        raise door.DoorError("That password is wrong.", "runtime")

    monkeypatch.setattr(door, "call", wrong)
    with pytest.raises(ef.EncryptedFolderError, match="wrong"):
        ef._mount("/c", "/mnt/encrypted/fam", "x")
    assert ef._unmount("/mnt/encrypted/fam") is False


def test_the_door_mounts_only_an_encrypted_folder_onto_kibotos_place(audit, monkeypatch, tmp_path):
    from backend import config, fsutil, proc
    from backend.services import encrypted_folders as ef

    store = tmp_path / "storage"
    cipher = store / "photos" / ".enc" / "fam"
    cipher.mkdir(parents=True)
    (cipher / "gocryptfs.conf").write_text("{}")
    monkeypatch.setattr(config, "POOL_PATH", str(store))
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [])
    mounted = []
    monkeypatch.setattr(ef, "_mount_here", lambda c, p, pw, ro=False, others=False: mounted.append((c, p, ro, others)))
    root = ef.ei.ROOT

    def mount(c, p, ro=False):
        return host_door.handle(
            {"op": "crypt.mount", "args": {"cipher": c, "plain": p, "password": "pw pw pw pw", "read_only": ro}}, 0
        )

    assert mount(str(cipher), f"{root}/fam")["ok"] and mounted == [(str(cipher), f"{root}/fam", False, True)]
    for c, p in (
        (str(cipher), "/etc/fam"),
        (str(cipher), f"{root}/a/b"),
        ("/etc", f"{root}/fam"),
        (str(store / "photos"), f"{root}/fam"),
    ):
        assert mount(c, p)["ok"] is False, (c, p)

    def refused(c, p, pw, ro=False, others=False):
        raise ef.EncryptedFolderError("That password is wrong.")

    monkeypatch.setattr(ef, "_mount_here", refused)
    reply = mount(str(cipher), f"{root}/fam")
    assert reply["ok"] is False and reply["kind"] == "runtime" and "wrong" in reply["error"]

    ran = []
    import subprocess

    monkeypatch.setattr(fsutil, "open_encrypted", lambda: {f"{root}/fam"})
    monkeypatch.setattr(
        proc, "run_bounded", lambda cmd, **kw: ran.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")
    )
    assert host_door.handle({"op": "crypt.unmount", "args": {"path": f"{root}/fam"}}, 0)["ok"] and ran == [
        ["umount", f"{root}/fam"]
    ]
    assert host_door.handle({"op": "crypt.unmount", "args": {"path": "/mnt/storage"}}, 0)["ok"] is False


def test_looking_on_the_drives_is_done_by_the_door(audit, monkeypatch, tmp_path):
    import types

    from backend import runtime
    from backend.services import pool_copy

    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    monkeypatch.setattr(pool_copy.os, "geteuid", lambda: 999)
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    calls = []
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, a)) or [{"key": "abc-tank"}])
    assert pool_copy.look() == [{"key": "abc-tank"}] and calls == [("pools.look", {"timeout": 1800})]

    found = tmp_path / "found"
    (found / "abc-tank").mkdir(parents=True)
    (found / "abc-tank" / "about.json").write_text("{}")
    monkeypatch.setattr(pool_copy, "FOUND", str(found))
    monkeypatch.setattr(pool_copy, "look", lambda run=None: [{"key": "abc-tank"}])
    owned = []
    monkeypatch.setattr(pool_copy.os, "chown", lambda p, u, g: owned.append((p, u, g)))
    import pwd

    monkeypatch.setattr(pwd, "getpwnam", lambda n: types.SimpleNamespace(pw_uid=999, pw_gid=987))
    assert host_door.handle({"op": "pools.look", "args": {}}, 0)["result"] == [{"key": "abc-tank"}]
    assert {o[0] for o in owned} == {str(found), str(found / "abc-tank"), str(found / "abc-tank" / "about.json")}
    assert all(o[1:] == (999, 987) for o in owned)

    def missing(n):
        raise KeyError(n)

    owned.clear()
    monkeypatch.setattr(pwd, "getpwnam", missing)
    assert pool_copy.look_in_door("kiboto") == [{"key": "abc-tank"}] and owned == []  # root reads it as it is


def test_the_copy_button_opens_a_card_through_the_door(audit, monkeypatch):
    from backend.services import copy_engine

    calls = []
    monkeypatch.setattr(copy_engine.os, "geteuid", lambda: 999)
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, a)) or copy_engine.CARD_MOUNT)
    monkeypatch.setattr(copy_engine, "local_offset_minutes", lambda: 660)  # the card clock zone goes along
    assert copy_engine.mount_card("/dev/sdc1") == copy_engine.CARD_MOUNT
    copy_engine.unmount_card()
    assert calls == [("copy.mount", {"device": "/dev/sdc1", "offset": 660}), ("copy.unmount", {})]

    def refused(op, **a):
        raise door.DoorError("only a card or stick that is not open anywhere", "value")

    monkeypatch.setattr(door, "call", refused)
    with pytest.raises(Exception, match="Failed to mount sdc1"):
        copy_engine.mount_card("/dev/sdc1")
    copy_engine.unmount_card()  # said in the log


def test_the_door_opens_only_a_card_that_is_open_nowhere(audit, monkeypatch):
    import json
    import subprocess

    from backend.services import copy_engine

    tree = {
        "blockdevices": [
            {
                "name": "sdc1",
                "rm": False,
                "hotplug": False,
                "tran": None,
                "mountpoints": [None],
                "children": [{"name": "sdc", "rm": True, "hotplug": True, "tran": "usb"}],
            }
        ]
    }
    monkeypatch.setattr(copy_engine.os.path, "realpath", lambda p: p)
    monkeypatch.setattr(copy_engine.os, "stat", lambda p: copy_engine.os.stat_result((0o060660,) + (0,) * 9))
    monkeypatch.setattr(
        copy_engine, "run_bounded", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, json.dumps(tree), "")
    )
    mounted = []
    monkeypatch.setattr(
        copy_engine, "_mount_card_here", lambda d, offset=0: mounted.append(d) or copy_engine.CARD_MOUNT
    )

    def card(device):
        return host_door.handle({"op": "copy.mount", "args": {"device": device, "offset": 660}}, 0)

    assert card("/dev/sdc1")["result"] == copy_engine.CARD_MOUNT and mounted == ["/dev/sdc1"]
    tree["blockdevices"][0]["mountpoints"] = ["/"]
    assert card("/dev/sdc1")["ok"] is False  # open already
    tree["blockdevices"][0]["mountpoints"] = [None]
    tree["blockdevices"][0]["children"][0].update(rm=False, hotplug=False, tran="sata")
    assert card("/dev/sdc1")["ok"] is False  # an inside drive
    monkeypatch.setattr(copy_engine.os, "stat", lambda p: copy_engine.os.stat_result((0o100644,) + (0,) * 9))
    assert card("/dev/sdc1")["ok"] is False  # not a drive
    assert len(mounted) == 1
    unmounted = []
    monkeypatch.setattr(copy_engine.os.path, "ismount", lambda p: True)
    monkeypatch.setattr(
        copy_engine,
        "run_bounded",
        lambda cmd, **kw: unmounted.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    assert host_door.handle({"op": "copy.unmount", "args": {}}, 0)["ok"] and unmounted == [
        ["umount", copy_engine.CARD_MOUNT]
    ]


def test_as_root_the_copy_button_opens_the_card_itself(monkeypatch, tmp_path):
    import subprocess

    from backend.services import copy_engine

    ran = []
    monkeypatch.setattr(copy_engine.os, "geteuid", lambda: 0)
    monkeypatch.setattr(copy_engine, "CARD_MOUNT", str(tmp_path / "card"))
    monkeypatch.setattr(
        copy_engine, "run_bounded", lambda cmd, **kw: ran.append(cmd) or subprocess.CompletedProcess(cmd, 0, b"", b"")
    )
    assert copy_engine.mount_card("/dev/sdc1") == str(tmp_path / "card")
    copy_engine.unmount_card()
    assert ran[0][0] == "mount" and "-r" in ran[0] and "nosuid,nodev,noexec" in ran[0][3] and ran[1][0] == "umount"
    monkeypatch.setattr(copy_engine, "run_bounded", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 32, b"", b""))
    with pytest.raises(Exception, match="Failed to mount sdc1"):
        copy_engine.mount_card("/dev/sdc1")
    monkeypatch.setattr(copy_engine.os.path, "ismount", lambda p: False)
    assert copy_engine.uncard_in_door() is True  # nothing open: nothing to close
    monkeypatch.setattr(copy_engine.os.path, "realpath", lambda p: p)
    monkeypatch.setattr(copy_engine.os, "stat", lambda p: copy_engine.os.stat_result((0o060660,) + (0,) * 9))
    monkeypatch.setattr(
        copy_engine, "run_bounded", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "not json", "")
    )
    with pytest.raises(ValueError):
        copy_engine.card_in_door("/dev/sdc1")  # lsblk said nothing readable: not opened


def test_the_door_is_restarted_only_when_it_runs_other_code(monkeypatch, tmp_path):
    from backend.services import native_update

    rel = tmp_path / "rel"
    (rel / "packaging").mkdir(parents=True)
    units = tmp_path / "units"
    units.mkdir()
    for name in native_update.UNITS:
        (rel / "packaging" / name).write_text(f"[Unit]\n# {name}\n")
        (units / name).write_text(f"[Unit]\n# {name}\n")
    ran = []

    def run(cmd, timeout=60):
        ran.append(cmd)
        return 0, ""

    native_update.ensure_units(str(rel), run, str(units), door_current=lambda: True)
    assert ran == []  # the same code: the door and what it opened stay
    native_update.ensure_units(str(rel), run, str(units), door_current=lambda: False)
    assert ran == [["systemctl", "restart", "kiboto-door.service"]]
    ran.clear()
    (rel / "packaging" / "kiboto-door.service").write_text("[Unit]\n# new\n")
    native_update.ensure_units(str(rel), run, str(units), door_current=lambda: True)
    assert ["systemctl", "restart", "kiboto-door.service"] in ran  # its unit changed


def test_door_version_and_current(monkeypatch):
    from backend import settings

    monkeypatch.setattr(settings, "current", lambda key: "abc123" if key == "build_commit" else "")
    mine = door.version()
    assert mine.startswith("abc123:") and len(mine.split(":")[1]) == 12
    assert host_door.handle({"op": "door.version", "args": {}}, 0)["result"] == host_door.LOADED  # as it started
    monkeypatch.setattr(door, "call", lambda op, **a: mine)
    assert door.current() is True
    monkeypatch.setattr(door, "call", lambda op, **a: "other:000000000000")
    assert door.current() is False

    def gone(op, **a):
        raise FileNotFoundError("no door")

    monkeypatch.setattr(door, "call", gone)
    assert door.current() is False


def test_an_encrypted_folder_whose_gocryptfs_ended_is_not_open(monkeypatch, tmp_path):
    import subprocess

    from backend import fsutil, proc
    from backend.services import encrypted_folders as ef

    plain = tmp_path / "fam"
    monkeypatch.setattr(ef, "plain_path", lambda name: str(plain))
    monkeypatch.setattr(ef, "_mounted", lambda: {str(plain)})
    assert ef.is_unlocked("fam") is False  # listed, but there is nothing at it
    plain.mkdir()
    assert ef.is_unlocked("fam") is True

    ran = []
    monkeypatch.setattr(fsutil, "open_encrypted", lambda: {str(tmp_path / "dead")})
    monkeypatch.setattr(
        proc, "run_bounded", lambda cmd, **kw: ran.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")
    )
    ef._clear_dead(str(tmp_path / "dead"))
    ef._clear_dead(str(plain))  # not listed: left alone
    assert ran == [["umount", "-l", str(tmp_path / "dead")]]


def test_cloud_folders_are_mounted_by_the_door_once_kiboto_is_not_root(audit, monkeypatch):
    from backend.services import rclone_engine

    eng = rclone_engine.RcloneEngine.__new__(rclone_engine.RcloneEngine)
    calls = []
    monkeypatch.setattr(rclone_engine.os, "geteuid", lambda: 999)
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, a)) or {"status": "mounted"})
    assert eng.mount_remote("gdrive", "Photos", "writes", False) == {"status": "mounted"}
    assert eng.unmount_remote("gdrive") == {"status": "mounted"}
    assert calls[0] == (
        "cloud.mount",
        {"name": "gdrive", "remote_path": "Photos", "vfs_cache": "writes", "read_only": False, "timeout": 120},
    )
    assert calls[1] == ("cloud.unmount", {"name": "gdrive"})
    host_door._checked({"op": "cloud.mount", "args": {k: v for k, v in calls[0][1].items() if k != "timeout"}})

    done = []

    class Engine:
        def mount_remote(self, *a):
            done.append(a)
            return {"status": "mounted"}

        def unmount_remote(self, name):
            done.append(name)
            return {"status": "unmounted"}

    monkeypatch.setattr(rclone_engine, "get_rclone_engine", lambda: Engine())

    def mount(**changes):
        args = {"name": "gdrive", "remote_path": "", "vfs_cache": "writes", "read_only": True, **changes}
        return host_door.handle({"op": "cloud.mount", "args": args}, 0)

    assert mount()["ok"] and done[-1] == ("gdrive", "", "writes", True)
    for bad in ({"name": "../etc"}, {"vfs_cache": "--rc"}, {"remote_path": "--config=/etc/x"}):
        assert mount(**bad)["ok"] is False, bad
    assert host_door.handle({"op": "cloud.unmount", "args": {"name": "gdrive"}}, 0)["result"] == {"status": "unmounted"}
    assert len(done) == 2


def test_the_door_version_follows_any_backend_file(tmp_path, monkeypatch):
    import os

    from backend import settings

    monkeypatch.setattr(settings, "current", lambda key: "abc" if key == "build_commit" else "")
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "nas_name.py").write_text("x = 1\n")
    (tmp_path / "door.py").write_text("y = 1\n")
    first = door.version(str(tmp_path))
    assert first.startswith("abc:") and door.version(str(tmp_path)) == first
    (tmp_path / "services" / "nas_name.py").write_text("x = 22\n")  # another file than the door's own
    assert door.version(str(tmp_path)) != first
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "z.py").write_text("")
    second = door.version(str(tmp_path))
    os.utime(tmp_path / "__pycache__" / "z.py", (1, 1))
    assert door.version(str(tmp_path)) == second  # compiled files do not count


def test_the_wrapped_key_comes_through_the_door(audit, monkeypatch):
    from backend import machine_key

    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: '{"v": 1}' if op == "keys.wrapped" else None)
    assert machine_key.wrapped_text() == '{"v": 1}'
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: False)
    import builtins
    import io

    real_open = builtins.open
    monkeypatch.setattr(
        builtins,
        "open",
        lambda p, *a, **k: io.StringIO('{"v": 2}') if str(p).endswith("data-key.recovery") else real_open(p, *a, **k),
    )
    assert machine_key.wrapped_text() == '{"v": 2}'
