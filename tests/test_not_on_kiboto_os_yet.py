"""On Kiboto OS the web process is not root (ADR 0006). Four features still need root work that
the host door does not do: each says "not available on Kiboto OS yet" instead of failing oddly.

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


def test_iscsi_says_not_yet_and_starts_nothing(kiboto_os, iscsi):
    for view in (iscsi_target.status(), iscsi_target.ensure()):
        assert view["running"] is False and view["why"] == "not_yet" and view["error"] == NOT_ON_OS_YET
    assert iscsi == []  # no systemctl, no systemd-run: it would only be refused


def test_iscsi_as_root_on_a_machine_of_its_own_still_runs_its_service(kiboto_os, iscsi, monkeypatch):
    monkeypatch.setattr(runtime, "is_root", lambda: True)
    assert iscsi_target.status()["why"] != "not_yet"
    assert iscsi and iscsi[0][:2] == ("systemctl", "is-active")


def test_the_iscsi_api_refuses_to_turn_it_on_or_add_a_disk(client, auth_headers, kiboto_os, iscsi):
    res = client.put("/api/iscsi/enabled", json={"enabled": True}, headers=auth_headers)
    assert res.status_code == 409 and res.json()["error"] == "not_on_kiboto_os"
    assert res.json()["text"] == {"msg_key": "srv.os_not_yet", "params": {}}
    disk = {"name": "x", "size_gb": 1, "folder": "/mnt/storage/tank", "user": "pc", "secret": "x" * 12}
    made = client.post("/api/iscsi/disks", json=disk, headers={**auth_headers, "X-Confirm-Token": "none"})
    assert made.status_code in (409, 428)  # asked to confirm first, or refused at once: never made
    assert client.get("/api/iscsi", headers=auth_headers).json()["why"] == "not_yet"


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


def test_sftp_refuses_to_start_and_stays_off(kiboto_os, sftp, monkeypatch):
    monkeypatch.setattr(sftp, "_unit", lambda *cmd: pytest.fail("nothing is started"))
    monkeypatch.setattr(sftp, "_check_port", lambda port: False)
    with pytest.raises(SaidError, match="not available on Kiboto OS yet"):
        sftp.start()
    assert sftp.get_config().get("enabled", False) is False  # the switch did not move
    sftp.save_config({"enabled": True})  # left on by a version before
    assert sftp.resume() is False


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


def test_the_sftp_api_says_why(client, auth_headers, kiboto_os, sftp, monkeypatch):
    monkeypatch.setattr("backend.api.sftp.get_sftp_engine", lambda: sftp)
    res = client.post("/api/sftp/toggle", json={"enabled": True}, headers=auth_headers)
    assert res.status_code == 409 and res.json()["error"] == "not_on_kiboto_os"
    assert res.json()["text"]["msg_key"] == "srv.os_not_yet"


# ── merged folders ──


def test_a_folder_that_would_fit_is_not_offered_a_merge_yet(kiboto_os, tmp_path, monkeypatch):
    fast, slow = tmp_path / "fast", tmp_path / "slow"
    (fast / "films").mkdir(parents=True)
    slow.mkdir()
    pools = [
        SimpleNamespace(id="fast", name="fast", mountpoint=str(fast), free_bytes=1),
        SimpleNamespace(id="slow", name="slow", mountpoint=str(slow), free_bytes=2),
    ]
    share = SimpleNamespace(mountpoint=str(fast / "films"), export_nfs=False)
    monkeypatch.setattr(tiering.tier_merge, "of", lambda path: None)
    monkeypatch.setattr(tiering.tier_merge, "missing", lambda path: pytest.fail("not asked on Kiboto OS"))
    assert tiering._own_pools_fit(share, pools) == {"why": "not_yet"}
    monkeypatch.setattr(runtime, "is_root", lambda: True)
    monkeypatch.setattr(tiering.tier_merge, "missing", lambda path: "no_tool")
    assert tiering._own_pools_fit(share, pools) == {"why": "no_merge_tool"}


# ── replication ──


class _Adapter:
    def get_platform_type(self):
        return SimpleNamespace(value="generic_linux")


def test_replication_is_not_offered_yet(kiboto_os, monkeypatch):
    from backend.hardware.pal import base

    monkeypatch.setattr(base, "storage_tools", lambda: {"zfs": True, "btrfs": True})
    assert replication_engine.availability(_Adapter()) == (False, NOT_ON_OS_YET)
    monkeypatch.setattr(runtime, "is_root", lambda: True)
    assert replication_engine.availability(_Adapter()) == (True, "")


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


def test_the_copy_button_says_it_is_not_read_yet(kiboto_os, monkeypatch, caplog):
    from backend.services import button_listener as bl

    with open(bl.__file__, encoding="utf-8") as f:
        src = f.read()
    at = src.index("except PermissionError as pe:")
    assert "runtime.without_root()" in src[at : at + 300]
    assert "not read on Kiboto OS yet" in src[at : at + 400]
