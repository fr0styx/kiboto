"""On Kiboto OS the web process is not root (ADR 0006). Features that still need root work the
host door does not do say "not available on Kiboto OS yet" instead of failing oddly; SFTP is now
started by the host door.

Found by trying them on the test machine: iSCSI and SFTP could not start their service ("Interactive
authentication required"), replication could not snapshot, and SFTP's status still said "running"
because the router answered on its port."""

from types import SimpleNamespace

import pytest

from backend import runtime
from backend.errors import NOT_ON_OS_YET, SaidError
from backend.services import iscsi_target, replication_engine, sftp_engine, tiering


@pytest.fixture
def kiboto_os(tmp_path, monkeypatch):
    """A machine Kiboto runs, with a web process that is not root."""
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    monkeypatch.setattr(runtime, "is_root", lambda: False)


def test_only_a_managed_machine_without_root_counts(kiboto_os, monkeypatch):
    assert runtime.without_root() is True
    monkeypatch.setattr(runtime, "is_root", lambda: True)  # a machine set up before the web user existed
    assert runtime.without_root() is False


def test_a_container_without_root_is_not_kiboto_os(monkeypatch):
    monkeypatch.setattr(runtime, "is_root", lambda: False)
    assert runtime.without_root() is False


def test_is_root_reads_the_process(monkeypatch):
    monkeypatch.undo()  # the real function, not the one every test is given
    monkeypatch.setattr(runtime.os, "geteuid", lambda: 999, raising=False)
    assert runtime.is_root() is False
    monkeypatch.setattr(runtime.os, "geteuid", lambda: 0, raising=False)
    assert runtime.is_root() is True


# ── iSCSI ──


@pytest.fixture
def iscsi(monkeypatch):
    disk = {"id": "d1", "name": "games", "folder": "/mnt/storage/tank/disks", "file": "games.img"}
    state = {"enabled": True, "disks": [{**disk, "size_gb": 10, "user": "pc", "secret": "x"}]}
    monkeypatch.setattr(iscsi_target, "_read", lambda: state)
    ran = []
    monkeypatch.setattr(
        iscsi_target, "_unit", lambda *cmd: ran.append(cmd) or (1, "Interactive authentication required.")
    )
    monkeypatch.setattr(iscsi_target, "_docker", lambda *a, **k: pytest.fail("no container on a machine of its own"))
    return ran


def test_iscsi_goes_through_the_host_door(kiboto_os, iscsi, monkeypatch):
    from backend import door

    asked = []
    answer = {"running": True, "why": ""}
    monkeypatch.setattr(door, "via", lambda op, here, **kw: asked.append((op, kw)) or answer)
    assert iscsi_target.ensure()["running"] is True
    op, kw = asked[-1]
    sent = kw["disks"][0]
    assert op == "iscsi.apply" and sent["file"] == "/mnt/storage/tank/disks/games.iscsi.img"
    assert sent["user"] == "pc" and sent["secret"] == "x" and sent["iqn"].endswith(":games")
    assert iscsi == []  # the web process starts nothing itself
    iscsi_target._read()["enabled"] = False
    iscsi_target.ensure()
    assert asked[-1] == ("iscsi.apply", {"disks": []})  # off: the door stops it
    iscsi_target._read()["enabled"] = True
    answer.update(running=False, why="start")
    view = iscsi_target.ensure()
    assert view["running"] is False and view["why"] == "start" and view["error"]


def test_iscsi_as_root_on_a_machine_of_its_own_still_runs_its_service(kiboto_os, iscsi, monkeypatch):
    monkeypatch.setattr(runtime, "is_root", lambda: True)
    assert iscsi_target.status()["why"] != "not_yet"
    assert iscsi and iscsi[0][:2] == ("systemctl", "is-active")


def test_the_iscsi_api_no_longer_refuses(client, auth_headers, kiboto_os, iscsi, monkeypatch):
    from backend import door

    monkeypatch.setattr(door, "via", lambda op, here, **kw: {"running": True, "why": ""})
    res = client.put("/api/iscsi/enabled", json={"enabled": True}, headers=auth_headers)
    assert res.json().get("error") != "not_on_kiboto_os"
    assert client.get("/api/iscsi", headers=auth_headers).json()["why"] != "not_yet"


def test_a_disk_file_is_made_and_removed_by_the_host_door(kiboto_os, iscsi, monkeypatch):
    from backend import door

    asked = []
    keys = iter(["", "file_exists"])
    monkeypatch.setattr(door, "via", lambda op, here, **kw: asked.append((op, kw)) or next(keys, True))
    disk = {"name": "games", "folder": "/mnt/storage/tank/disks", "size_gb": 10}
    iscsi_target._make_file(disk, grow_only=False)
    assert asked[-1] == (
        "iscsi.make_file",
        {"path": "/mnt/storage/tank/disks/games.iscsi.img", "size_gb": 10, "fresh": True},
    )
    with pytest.raises(iscsi_target.DiskError) as e:
        iscsi_target._make_file(disk, grow_only=True)
    assert e.value.key == "file_exists" and asked[-1][1]["fresh"] is False
    monkeypatch.setattr(iscsi_target, "atomic_write_json", lambda path, data: None)
    iscsi_target.delete("d1", with_file=True)
    assert asked[-1] == ("iscsi.remove_file", {"path": "/mnt/storage/tank/disks/games.iscsi.img"})


@pytest.fixture
def door_side(tmp_path, monkeypatch):
    """The host door's side: a storage folder, Kiboto's own folder beside it, and the unit recorded."""
    from backend import config

    pool = tmp_path / "storage" / "tank" / "disks"
    pool.mkdir(parents=True)
    monkeypatch.setattr(config, "POOL_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(iscsi_target, "DATA_DIR", str(tmp_path / "storage" / "tank" / "kiboto-data"))
    monkeypatch.setattr(iscsi_target, "ROOT_SETUP", str(tmp_path / "etc" / "iscsi" / "setup.sh"))
    ran = []

    def unit(*cmd):
        ran.append(cmd)
        return (3, "inactive") if cmd[:2] == ("systemctl", "is-active") else (0, "")

    monkeypatch.setattr(iscsi_target, "_unit", unit)
    return pool, ran


def _sent(pool, **over):
    return {
        "iqn": iscsi_target.IQN_PREFIX + ":nas:games",
        "file": str(pool / "games.iscsi.img"),
        "user": "pc",
        "secret": "a-good-secret",
        "allow": "",
        **over,
    }


def test_the_door_writes_its_own_script_from_checked_disks(door_side, tmp_path):
    pool, ran = door_side
    assert iscsi_target.apply_here([_sent(pool)]) == {"running": True, "why": ""}
    setup = tmp_path / "etc" / "iscsi" / "setup.sh"
    assert setup.stat().st_mode & 0o777 == 0o600 and "--password a-good-secret" in setup.read_text()
    started = next(c for c in ran if c[0] == "systemd-run")
    assert f"sh {setup}" in started[-1]  # its own copy, never the web process's file
    assert iscsi_target.apply_here([]) == {"running": False, "why": ""}


@pytest.mark.parametrize(
    "over",
    [
        {"iqn": "iqn.2000-01.com.evil:x"},
        {"user": "pc; reboot"},
        {"secret": "short"},
        {"allow": "everyone"},
        {"file": "/etc/shadow"},
        {"file": "relative/games.iscsi.img"},
        {"secret": None},
    ],
)
def test_the_door_refuses_a_disk_that_is_not_kibotos(door_side, over):
    pool, ran = door_side
    with pytest.raises(ValueError):
        iscsi_target.apply_here([_sent(pool, **over)])
    assert not [c for c in ran if c[0] == "systemd-run"]


def test_the_door_touches_only_kibotos_disk_files(door_side, tmp_path):
    pool, _ = door_side
    good = str(pool / "games.iscsi.img")
    assert iscsi_target.make_file_here(good, 1, True) == ""
    assert (pool / "games.iscsi.img").stat().st_size == 1024**3
    assert iscsi_target.make_file_here(good, 1, True) == "file_exists"
    assert (
        iscsi_target.make_file_here(good, 2, False) == "" and (pool / "games.iscsi.img").stat().st_size == 2 * 1024**3
    )
    (tmp_path / "elsewhere").mkdir()
    (pool / "link").symlink_to(tmp_path / "elsewhere")
    data = tmp_path / "storage" / "tank" / "kiboto-data"
    data.mkdir()
    for bad in (
        str(pool / "link" / "games.iscsi.img"),  # through a link
        str(data / "games.iscsi.img"),  # in Kiboto's own folder
        str(pool / "games.img"),  # not a disk file's name
        str(tmp_path / "games.iscsi.img"),  # outside the storage folder
    ):
        with pytest.raises(ValueError):
            iscsi_target.make_file_here(bad, 1, True)
    for size in (0, True, 10**9):
        with pytest.raises(ValueError):
            iscsi_target.make_file_here(good, size, False)
    with pytest.raises(ValueError):
        iscsi_target.apply_here([_sent(pool)] * (iscsi_target.MAX_DISKS + 1))
    assert iscsi_target.remove_file_here(good) is True and not (pool / "games.iscsi.img").exists()
    assert iscsi_target.remove_file_here(good) is True  # already gone


def test_the_door_has_the_iscsi_operations():
    from backend.services import host_door

    assert host_door.OPERATIONS["iscsi.apply"].args == {"disks": (list,)}
    assert host_door.OPERATIONS["iscsi.make_file"].args == {"path": (str,), "size_gb": (int,), "fresh": (bool,)}
    assert host_door.OPERATIONS["iscsi.remove_file"].args == {"path": (str,)}


# ── SFTP ──


@pytest.fixture
def sftp(tmp_path, monkeypatch):
    monkeypatch.setattr(sftp_engine, "SFTP_DIR", str(tmp_path / "sftp"))
    monkeypatch.setattr(sftp_engine, "SFTP_CONFIG_FILE", str(tmp_path / "sftp" / "config.json"))
    monkeypatch.setattr(sftp_engine, "SFTP_USERS_FILE", str(tmp_path / "sftp" / "users.json"))
    monkeypatch.setattr(sftp_engine, "SFTP_CONF_FILE", str(tmp_path / "sftp" / "sshd_config"))
    (tmp_path / "sftp").mkdir()
    monkeypatch.setattr(sftp_engine, "docker_sock", lambda: str(tmp_path / "no-socket"))
    return sftp_engine.SFTPEngine()


def test_sftp_is_started_and_stopped_by_the_host_door(kiboto_os, sftp, monkeypatch):
    from backend import door

    asked = []
    monkeypatch.setattr(door, "via", lambda op, here, **kw: asked.append((op, kw)) or True)
    ran = []
    monkeypatch.setattr(sftp, "_unit", lambda *cmd: ran.append(cmd) or (3, "inactive"))
    monkeypatch.setattr(sftp, "_check_port", lambda port: False)
    monkeypatch.setattr(sftp, "_start_subprocess", lambda port: pytest.fail("no process inside Kiboto"))
    monkeypatch.setattr(sftp_engine.time, "sleep", lambda s: None)
    sftp.start()
    assert asked == [("sftp.start", {"port": 2222})] and sftp.get_config()["enabled"] is True
    sftp.stop()
    assert asked[-1] == ("sftp.stop", {}) and sftp.get_config()["enabled"] is False
    sftp.save_config({"enabled": True})  # on at Kiboto's start: served again, through the door
    monkeypatch.setattr(sftp, "start", lambda: asked.append(("start", {})))
    assert sftp.resume() is True and asked[-1] == ("start", {})
    # it only asked whether the service runs: nothing started or stopped by the web process itself
    assert all(cmd[:2] == ("systemctl", "is-active") for cmd in ran)


def test_the_door_runs_the_service_as_kibotos_own_user(sftp, monkeypatch):
    from backend.services import host_basics

    seen = []
    monkeypatch.setattr(host_basics, "run", lambda cmd, timeout=30: seen.append(cmd) or (0, "inactive"))
    assert sftp_engine.start_unit_here(2222) is True
    started = seen[-1]
    assert started[0] == "systemd-run" and "User=kiboto" in started and "Group=users" in started
    assert "UMask=0002" in started and "NoNewPrivileges=yes" in started
    assert not any(a.startswith("AmbientCapabilities") for a in started)  # no rights beyond the user's
    assert "User=kiboto" not in sftp_engine.unit_command(2222, "/c")  # as root where Kiboto is root
    for port in (22, 70000, True, "2222"):
        with pytest.raises(ValueError):
            sftp_engine.start_unit_here(port)
    assert sftp_engine.stop_unit_here() is True and seen[-1] == ["systemctl", "stop", "kiboto-sftp"]
    monkeypatch.setattr(host_basics, "run", lambda cmd, timeout=30: (1, "refused"))
    assert sftp_engine.start_unit_here(2222) is False


def test_the_door_has_the_sftp_operations():
    from backend.services import host_door

    assert host_door.OPERATIONS["sftp.start"].args == {"port": (int,)}
    assert host_door.OPERATIONS["sftp.stop"].args == {}


def test_the_routers_port_is_not_this_machines(kiboto_os, sftp, monkeypatch):
    assert sftp._gateway() == ""
    asked = []

    class Sock:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, t):
            pass

        def connect(self, where):
            pass

        def getsockname(self):
            return ("192.168.1.50", 0)

        def connect_ex(self, where):
            asked.append(where[0])
            return 1

    monkeypatch.setattr(sftp_engine.socket, "socket", Sock)
    assert sftp._check_port(2222) is False
    assert "127.0.0.1" in asked and "192.168.1.1" not in asked and "10.0.2.2" not in asked


def test_in_a_container_the_gateway_is_the_host_and_is_asked(sftp, monkeypatch, tmp_path):
    route = tmp_path / "route"
    route.write_text("Iface\tDestination\tGateway\neth0\t00000000\t0101A8C0\t0003\n")
    real_open = open
    monkeypatch.setattr("builtins.open", lambda p, *a, **k: real_open(route if p == "/proc/net/route" else p, *a, **k))
    assert sftp._gateway() == "192.168.1.1"


def test_the_sftp_api_turns_it_on_through_the_door(client, auth_headers, kiboto_os, sftp, monkeypatch):
    from backend import door

    asked = []
    monkeypatch.setattr(door, "via", lambda op, here, **kw: asked.append(op) or True)
    monkeypatch.setattr(sftp, "_check_port", lambda port: False)
    monkeypatch.setattr(sftp, "_start_subprocess", lambda port: None)
    monkeypatch.setattr(sftp_engine.time, "sleep", lambda s: None)
    monkeypatch.setattr("backend.api.sftp.get_sftp_engine", lambda: sftp)
    res = client.post("/api/sftp/toggle", json={"enabled": True}, headers=auth_headers)
    assert res.status_code == 200 and asked == ["sftp.start"]


# ── merged folders ──


def test_a_folder_that_would_fit_is_offered_a_merge(kiboto_os, tmp_path, monkeypatch):
    fast, slow = tmp_path / "fast", tmp_path / "slow"
    (fast / "films").mkdir(parents=True)
    slow.mkdir()
    pools = [
        SimpleNamespace(id="fast", name="fast", mountpoint=str(fast), free_bytes=1),
        SimpleNamespace(id="slow", name="slow", mountpoint=str(slow), free_bytes=2),
    ]
    share = SimpleNamespace(mountpoint=str(fast / "films"), export_nfs=False)
    monkeypatch.setattr(tiering.tier_merge, "of", lambda path: None)
    monkeypatch.setattr(tiering.tier_merge, "missing", lambda path: "")
    fit = tiering._own_pools_fit(share, pools)  # offered on Kiboto OS too: the host door merges it
    assert fit["why"] == "" and fit["kind"] == "merged" and [c["id"] for c in fit["slow_choices"]] == ["slow"]
    monkeypatch.setattr(tiering.tier_merge, "missing", lambda path: "no_tool")
    assert tiering._own_pools_fit(share, pools) == {"why": "no_merge_tool"}


# ── replication ──


class _Adapter:
    def get_platform_type(self):
        return SimpleNamespace(value="generic_linux")


def test_replication_is_offered_and_runs_in_the_host_door(kiboto_os, monkeypatch, tmp_path):
    from backend import door
    from backend.hardware.pal import base

    monkeypatch.setattr(base, "storage_tools", lambda: {"zfs": True, "btrfs": True})
    assert replication_engine.availability(_Adapter()) == (True, "")
    asked = []
    monkeypatch.setattr(door, "via", lambda op, here, **kw: asked.append((op, kw)) or {"bytes": 5, "snapshot": "s"})
    monkeypatch.setattr(replication_engine, "replicate", lambda job: pytest.fail("the web process has no root"))
    monkeypatch.setattr(replication_engine, "REPLICATION_JOBS_FILE", str(tmp_path / "jobs.json"))
    monkeypatch.setattr(replication_engine, "REPLICATION_HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setattr(replication_engine, "_finished", lambda *a: None)
    engine = replication_engine.ReplicationEngine()
    job = engine.create_job({"name": "n", "source_pool": "fast", "target_pool": "big"})
    engine._execute(job)
    assert asked == [("replication.run", {"job": job})]
    assert engine.get_job(job["id"])["last_status"] == "success"


def test_on_kiboto_os_a_copy_stays_on_this_machine(kiboto_os):
    remote = {"source_pool": "fast", "target_pool": "big", "target_type": "ssh", "target_host": "h", "target_user": "u"}
    with pytest.raises(ValueError, match="not available on Kiboto OS yet"):
        replication_engine.validate(remote)
    with pytest.raises(ValueError, match="not available on Kiboto OS yet"):
        replication_engine.run_here(remote)


def test_the_door_copies_only_between_this_machines_pools(monkeypatch):
    from backend.hardware import pal_storage

    pools = [SimpleNamespace(id="fast"), SimpleNamespace(id="big")]
    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: SimpleNamespace(list_pools=lambda: pools))
    ran = []
    monkeypatch.setattr(replication_engine, "replicate", lambda job, adapter=None: ran.append(job) or {"bytes": 1})
    assert replication_engine.run_here({"source_pool": "fast", "target_pool": "big"}) == {"bytes": 1}
    for job in ({"source_pool": "fast", "target_pool": "elsewhere"}, {"source_pool": "../x", "target_pool": "big"}, []):
        with pytest.raises(ValueError):
            replication_engine.run_here(job)
    assert len(ran) == 1


def test_the_door_has_the_replication_operation():
    from backend import door
    from backend.services import host_door

    assert host_door.OPERATIONS["replication.run"].args == {"job": (dict,)}
    assert door.LONG["replication.run"] >= 86400


def test_the_replication_list_carries_the_sentence_for_the_readers_language(client, auth_headers, monkeypatch):
    monkeypatch.setattr("backend.api.replication.availability", lambda: (False, NOT_ON_OS_YET))
    body = client.get("/api/storage/replication/jobs", headers=auth_headers).json()
    assert body["available"] is False and body["text"] == {"msg_key": "srv.os_not_yet", "params": {}}
    monkeypatch.setattr("backend.api.replication.availability", lambda: (False, "Unraid's pools are replicated…"))
    assert client.get("/api/storage/replication/jobs", headers=auth_headers).json()["text"] is None
    res = client.post(
        "/api/storage/replication/jobs",
        json={"name": "n", "source_pool": "a", "target_pool": "b"},
        headers=auth_headers,
    )
    assert res.status_code == 409


# ── the front COPY button ──


def test_on_kiboto_os_the_copy_button_is_read_by_the_host_door(kiboto_os, monkeypatch):
    from backend import door
    from backend.services import button_listener as bl

    answers = iter([True, False, door.DoorError("refused")])
    asked, pressed, paused = [], [], []

    def call(op, timeout=None, **kw):
        asked.append((op, kw, timeout))
        got = next(answers)
        if isinstance(got, Exception):
            raise got
        return got

    monkeypatch.setattr(door, "call", call)
    monkeypatch.setattr(bl, "handle_press", lambda: pressed.append(1))
    bl.through_door(rounds=3, pause=paused.append)
    assert asked[0] == ("button.wait", {"seconds": bl.DOOR_WAIT_SECS}, bl.DOOR_WAIT_SECS + 60)
    assert pressed == [1] and paused == [0.3, 60]  # one press; a refusal waits a minute


def test_a_press_is_down_twice_50_ms_apart():
    from backend.services import button_listener as bl

    now = [0.0]

    def sleep(s):
        now[0] += s

    values = iter([2, 2, 0, 0])  # up, up, down, still down
    assert bl.wait_press(lambda: next(values), 10, sleep=sleep, clock=lambda: now[0]) is True
    bounce = iter([0, 2] + [2] * 100)  # down for a moment only, then up: no press
    assert bl.wait_press(lambda: next(bounce), 5, sleep=sleep, clock=lambda: now[0]) is False


def test_the_door_waits_only_on_a_zettlab_and_for_a_sane_time(monkeypatch):
    from backend.hardware import fans
    from backend.services import button_listener as bl
    from backend.services import host_door

    for seconds in (0, 5000, True):
        with pytest.raises(ValueError):
            bl.wait_here(seconds)
    monkeypatch.setattr(fans, "is_zettlab_appliance", lambda: False)
    with pytest.raises(ValueError, match="no front COPY button"):
        bl.wait_here(10)
    assert host_door.OPERATIONS["button.wait"].args == {"seconds": (int,)}
