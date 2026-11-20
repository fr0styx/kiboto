"""New Samba settings are applied without restarting the file server. A restart cut every
connection, also for a change to one shared folder or one blocked address. Reloaded settings
count for new connections only, so the shared folders whose section changed are closed and the
connections of newly blocked addresses are ended (tried with the real smbd on 20 Nov 2026)."""

import subprocess

import pytest

from backend.services import samba_engine
from backend.services.samba_engine import SambaShareConfig, conf_sections, only_lets_more_in, what_changed

OLD = """[global]
   workgroup = WORKGROUP
   hosts deny = 10.0.0.9

[homes]
   path = /mnt/storage/homes/%S
   read only = no

[Films]
   path = /mnt/storage/Films
   valid users = ana kim

[Music]
   path = /mnt/storage/Music
   valid users = ana

[Old]
   path = /mnt/storage/Old
"""


def test_an_smb_conf_by_section():
    found = conf_sections(OLD)
    assert sorted(found) == ["Films", "Music", "Old", "global", "homes"]
    assert found["Films"] == "path = /mnt/storage/Films\nvalid users = ana kim"
    assert conf_sections("") == {} and conf_sections("   stray = line\n") == {}


def test_what_a_new_smb_conf_changes():
    assert what_changed(OLD, OLD) == {"shares": [], "ips": [], "homes": False}
    new = (
        OLD.replace("valid users = ana kim", "valid users = ana")  # kim loses Films
        .replace("hosts deny = 10.0.0.9", "hosts deny = 10.0.0.9 10.0.0.7")  # one more address blocked
        .replace("[Old]\n   path = /mnt/storage/Old\n", "[New]\n   path = /mnt/storage/New\n")  # one gone, one new
    )
    # the changed and the removed share are closed; a new one has nobody connected; Music is left alone
    assert what_changed(OLD, new) == {"shares": ["Films", "Old"], "ips": ["10.0.0.7"], "homes": False}
    frozen = OLD.replace("   read only = no", "   read only = yes")
    assert what_changed(OLD, frozen)["homes"] is True  # private folders cannot be closed by name
    assert what_changed("", OLD) == {"shares": [], "ips": ["10.0.0.9"], "homes": False}  # nothing before


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self.body = status, body or {}

    def json(self):
        return self.body


class Docker:
    """The Docker socket, as far as reload_service uses it."""

    def __init__(self, exec_status=201, exit_code=0):
        self.exec_status, self.exit_code, self.calls = exec_status, exit_code, []

    def __call__(self, **kw):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None):
        self.calls.append((url.split("localhost", 1)[1], json))
        if url.endswith("/exec"):
            return Resp(self.exec_status, {"Id": "e1"})
        return Resp(204 if "/restart" in url else 200)

    def get(self, url):
        return Resp(200, {"ExitCode": self.exit_code})


@pytest.fixture
def engine(tmp_path, monkeypatch):
    import httpx

    sock = tmp_path / "docker.sock"
    sock.write_text("")
    monkeypatch.setattr(samba_engine, "_docker_sock_path", lambda: str(sock))
    monkeypatch.setattr(samba_engine, "SAMBA_CONF_FILE", str(tmp_path / "smb.conf"))
    monkeypatch.setattr(samba_engine, "validate_share", lambda s: None)
    monkeypatch.setattr(samba_engine, "access_lines", lambda share: [f"   valid users = {share.comment}"])
    monkeypatch.setattr(samba_engine, "_serves_files", lambda: False)
    monkeypatch.setattr(httpx, "HTTPTransport", lambda uds: None)

    def no_smbcontrol(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(subprocess, "run", no_smbcontrol)
    made = samba_engine.SambaEngine.__new__(samba_engine.SambaEngine)
    made._shares = {
        "Films": SambaShareConfig(name="Films", path=str(tmp_path / "Films"), comment="ana kim"),
        "Music": SambaShareConfig(name="Music", path=str(tmp_path / "Music"), comment="ana"),
    }
    monkeypatch.setattr(made, "check_sidecar", lambda: {"detected": True, "id": "abc123"})
    return made


def _docker(monkeypatch, **how):
    import httpx

    made = Docker(**how)
    monkeypatch.setattr(httpx, "Client", made)
    return made


def test_a_change_to_one_shared_folder_closes_that_one_and_restarts_nothing(engine, monkeypatch):
    engine.generate_and_save_conf()  # the first settings: nothing to compare with
    assert engine._changed is None
    docker = _docker(monkeypatch)
    assert engine.reload_service() is True and "/restart" in docker.calls[0][0]  # so the server is restarted
    engine._shares["Films"].comment = "ana"  # kim loses Films
    engine.generate_and_save_conf()
    assert engine._changed == {"shares": ["Films"], "ips": [], "homes": False}
    docker = _docker(monkeypatch)
    assert engine.reload_service() is True
    paths = [path for path, _body in docker.calls]
    assert paths == ["/containers/abc123/exec", "/exec/e1/start"]  # no restart
    cmd = docker.calls[0][1]["Cmd"]
    assert cmd[:2] == ["sh", "-c"] and cmd[2] == samba_engine.RELOAD_SCRIPT and cmd[3:] == ["--", "Films", "--ips"]
    assert engine._changed is None  # used up: the next reload without new settings knows nothing


def test_the_file_server_is_restarted_when_a_reload_is_not_enough_or_does_not_work(engine, monkeypatch):
    def restarted(docker):
        return [path for path, _body in docker.calls if "/restart" in path] == ["/containers/abc123/restart?t=2"]

    # nothing is known about what changed (the Reload button, the first settings)
    docker = _docker(monkeypatch)
    engine._changed = None
    assert engine.reload_service() is True and restarted(docker) and len(docker.calls) == 1
    # the private folders' section changed: they cannot be closed by name
    docker = _docker(monkeypatch)
    engine._changed = {"shares": [], "ips": [], "homes": True}
    assert engine.reload_service() is True and restarted(docker) and len(docker.calls) == 1
    # the script could not be started, or it ended badly: the restart still applies the settings
    for how in ({"exec_status": 409}, {"exit_code": 1}):
        docker = _docker(monkeypatch, **how)
        engine._changed = {"shares": ["Films"], "ips": ["10.0.0.7"], "homes": False}
        assert engine.reload_service() is True and restarted(docker), how
        assert docker.calls[0][1]["Cmd"][3:] == ["--", "Films", "--ips", "10.0.0.7"]


def test_the_script_names_what_samba_understands():
    script = samba_engine.RELOAD_SCRIPT
    for needed in ("all reload-config", "all close-share", "all kill-client-ip", "pdbedit -L", "adduser -D -H"):
        assert needed in script, needed
    assert "/etc/samba/kiboto/smb.conf" in script  # where docker-compose.linux.yml mounts Kiboto's settings
    with open("docker-compose.linux.yml", encoding="utf-8") as f:
        assert "/etc/samba/kiboto/smb.conf" in f.read()


def test_settings_written_twice_before_one_reload_close_what_either_changed(engine, monkeypatch):
    engine.generate_and_save_conf()
    docker = _docker(monkeypatch)
    engine.reload_service()  # the first settings are in place
    engine._shares["Films"].comment = "ana"
    engine.generate_and_save_conf()  # Films changed, and nobody reloaded
    engine._shares["Music"].comment = "ana kim"
    engine.generate_and_save_conf()  # then Music changed
    assert engine._changed == {"shares": ["Films", "Music"], "ips": [], "homes": False}
    docker = _docker(monkeypatch)
    assert engine.reload_service() is True
    assert docker.calls[0][1]["Cmd"][3:] == ["--", "Films", "Music", "--ips"]
    engine.generate_and_save_conf()  # nothing new after the reload
    assert engine._changed == {"shares": [], "ips": [], "homes": False}
    assert samba_engine._both(None, {"shares": [], "ips": [], "homes": False}) is None  # unknown stays unknown
    assert samba_engine._both(
        {"shares": ["a"], "ips": ["1.1.1.1"], "homes": False}, {"shares": [], "ips": [], "homes": True}
    ) == {
        "shares": ["a"],
        "ips": ["1.1.1.1"],
        "homes": True,
    }


def test_a_shared_folder_is_closed_only_when_someone_loses_something():
    base = "path = /mnt/storage/Films\nread only = no\nvalid users = admin ana"

    def with_people(valid, readers=""):
        return f"path = /mnt/storage/Films\nread only = no\nvalid users = {valid}" + (
            f"\nread list = {readers}" if readers else ""
        )

    assert only_lets_more_in(base, with_people("admin ana kim")) is True  # a new person
    assert only_lets_more_in(base, with_people("admin ana kim", "kim")) is True  # who may only read
    assert only_lets_more_in(with_people("admin ana", "ana"), base) is True  # ana may write now
    assert only_lets_more_in(base, with_people("admin")) is False  # ana is out
    assert only_lets_more_in(base, with_people("admin ana", "ana")) is False  # ana may only read now
    assert only_lets_more_in(base, base.replace("read only = no", "read only = yes")) is False  # frozen
    assert only_lets_more_in("path = /x", "path = /x\nvalid users = admin") is False  # it named nobody before
    assert only_lets_more_in(base, "path = /mnt/storage/Films\nread only = no") is False
    # adding a person changes every share's list and closes none of them
    new = OLD.replace("valid users = ana kim", "valid users = ana kim leo").replace(
        "valid users = ana\n", "valid users = ana leo\n"
    )
    assert new != OLD and what_changed(OLD, new) == {"shares": [], "ips": [], "homes": False}
