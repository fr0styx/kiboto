"""SFTP that is on stays on across a restart of Kiboto; on a machine of its own it is a service."""

import pytest

from backend import runtime
from backend.services import host_basics, sftp_engine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(sftp_engine, "SFTP_DIR", str(tmp_path / "sftp"))
    monkeypatch.setattr(sftp_engine, "SFTP_CONFIG_FILE", str(tmp_path / "sftp" / "config.json"))
    monkeypatch.setattr(sftp_engine, "SFTP_USERS_FILE", str(tmp_path / "sftp" / "users.json"))
    monkeypatch.setattr(sftp_engine, "SFTP_CONF_FILE", str(tmp_path / "sftp" / "sshd_config"))
    (tmp_path / "sftp").mkdir()
    e = sftp_engine.SFTPEngine()
    monkeypatch.setattr(e, "_check_port", lambda port: False)
    monkeypatch.setattr(sftp_engine, "docker_sock", lambda: str(tmp_path / "no-socket"))
    return e


@pytest.fixture
def managed(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    seen, unit = [], {"on": False}

    def run(cmd, timeout=20):
        seen.append(cmd)
        if cmd[:2] == ["systemctl", "is-active"]:
            return (0, "active") if unit["on"] else (3, "inactive")
        if cmd[0] == "systemd-run":
            unit["on"] = True
        if cmd[:2] == ["systemctl", "stop"]:
            unit["on"] = False
        return 0, ""

    monkeypatch.setattr(host_basics, "run", run)
    return seen, unit


def test_kiboto_stopping_leaves_the_setting_and_the_service_alone(engine, managed):
    seen, unit = managed
    engine.save_config({"enabled": True})
    unit["on"] = True
    engine.shutdown()
    assert engine.get_config()["enabled"] is True
    assert not [c for c in seen if c[:2] == ["systemctl", "stop"]]


def test_on_a_machine_of_its_own_sftp_is_a_service_of_the_machine(engine, managed, monkeypatch):
    seen, unit = managed
    monkeypatch.setattr(engine, "_start_subprocess", lambda port: pytest.fail("no process inside Kiboto"))
    monkeypatch.setattr(sftp_engine.time, "sleep", lambda s: None)
    engine.start()
    started = next(c for c in seen if c[0] == "systemd-run")
    assert started[started.index("--unit") + 1] == "kiboto-sftp" and "Restart=always" in started
    assert started[-3:-1] == [sftp_engine.FRONT_SCRIPT, "2222"]
    assert engine.get_status().mode == "service"
    engine.stop()
    assert ["systemctl", "stop", "kiboto-sftp"] in seen and unit["on"] is False
    assert engine.get_config()["enabled"] is False  # turned off by the person: off


def test_sftp_that_is_on_serves_again_at_the_start(engine, managed, monkeypatch):
    started = []
    monkeypatch.setattr(engine, "start", lambda: started.append(1))
    assert engine.resume() is False  # off: nothing
    engine.save_config({"enabled": True})
    assert engine.resume() is True and started == [1]
    monkeypatch.setattr(engine, "_check_port", lambda port: True)
    assert engine.resume() is False  # already serving (a helper container kept running)


def test_the_fallback_process_ends_with_kiboto(engine):
    class Proc:
        def __init__(self):
            self.done = []

        def terminate(self):
            self.done.append("terminate")

        def wait(self, timeout=None):
            self.done.append("wait")

    engine._proc = proc = Proc()
    engine.shutdown()
    assert proc.done == ["terminate", "wait"] and engine._proc is None
    engine.shutdown()  # nothing running: nothing to do
