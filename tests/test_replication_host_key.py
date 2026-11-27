"""A copy to another machine whose identity (SSH host key) is not the one Kiboto remembered: said in
words, and the remembered key can be forgotten once that machine was reinstalled. Tried on Kiboto
OS: after the other machine got new host keys every run failed with ssh's own "Host key
verification failed", shown only in a tooltip, and nothing short of a root shell could fix it."""

import os

import pytest

from backend import door, runtime
from backend.services import host_basics, host_door
from backend.services import replication_engine as re_


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(re_, "REPLICATION_JOBS_FILE", str(tmp_path / "jobs.json"))
    monkeypatch.setattr(re_, "REPLICATION_HISTORY_FILE", str(tmp_path / "history.json"))
    e = re_.ReplicationEngine()
    re_.atomic_write_json(re_.REPLICATION_JOBS_FILE, [{"id": "j1", "name": "off-site", "target_type": "remote_ssh"}])
    return e


def test_a_changed_host_key_is_said_in_words_with_a_key_and_a_good_run_clears_it(engine):
    engine.update_job_status("j1", "error", "receive failed: Host key verification failed.")
    job = engine.get_job("j1")
    assert job["last_error"] == re_.HOST_KEY_SAID and job["last_error_key"] == re_.CHANGED_HOST
    engine.update_job_status("j1", "error", "receive failed: out of space")
    assert engine.get_job("j1")["last_error_key"] is None
    engine.update_job_status("j1", "success")
    assert engine.get_job("j1")["last_error"] is None


def test_a_machine_met_for_the_first_time_is_remembered_with_or_without_a_key_of_its_own():
    job = {"target_type": "remote_ssh", "target_host": "backup.lan", "target_user": "kopie"}
    for side in (re_._Side(job), re_._Side(job, "/etc/kiboto/replication/id_ed25519")):
        assert "StrictHostKeyChecking=accept-new" in side.ssh
    assert "UserKnownHostsFile=/etc/kiboto/replication/known_hosts" in re_._Side(job, re_.KEY).ssh


def test_forgetting_a_remembered_key(tmp_path, monkeypatch):
    known = tmp_path / "known_hosts"
    ran, said = [], {"text": "# Host backup.lan found: line 1\n/known_hosts updated."}
    monkeypatch.setattr(host_basics, "run", lambda cmd, timeout=20: (ran.append(cmd), (0, said["text"]))[1])
    assert re_._forget_in("backup.lan", 22, str(known)) is False and ran == []  # nothing remembered yet
    known.write_text("x\n")
    assert re_._forget_in("backup.lan", 22, str(known)) is True
    assert ran[-1] == ["ssh-keygen", "-R", "backup.lan", "-f", str(known)]
    re_._forget_in("backup.lan", 2222, str(known))
    assert ran[-1][2] == "[backup.lan]:2222"
    said["text"] = "Host backup.lan not found in known_hosts"
    assert re_._forget_in("backup.lan", 22, str(known)) is False
    monkeypatch.setattr(re_, "KEY_DIR", str(tmp_path))
    said["text"] = "updated"
    assert re_.forget_host_here("backup.lan", 22) is True
    for host, port in (("-oProxyCommand=x", 22), ("a b", 22), ("backup.lan", 0), ("backup.lan", True), (5, 22)):
        with pytest.raises(ValueError):
            re_.forget_host_here(host, port)


def test_on_kiboto_os_the_root_service_forgets_it_and_elsewhere_the_users_own_list(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(runtime, "without_root", lambda: True)
    monkeypatch.setattr(door, "via", lambda op, here, **kw: asked.append((op, kw)) or True)
    assert re_.forget_host("backup.lan", 22) is True and asked == [
        ("replication.forget_host", {"host": "backup.lan", "port": 22})
    ]
    monkeypatch.setattr(runtime, "without_root", lambda: False)
    monkeypatch.setattr(re_.os.path, "expanduser", lambda p: str(tmp_path))
    seen = []
    monkeypatch.setattr(re_, "_forget_in", lambda host, port, known: seen.append(known) or True)
    assert re_.forget_host("backup.lan", 22) is True and seen == [os.path.join(str(tmp_path), ".ssh", "known_hosts")]


def test_the_root_service_has_the_operation(monkeypatch):
    monkeypatch.setattr(re_, "forget_host_here", lambda host, port: (host, port) == ("backup.lan", 22))
    reply = host_door.handle({"op": "replication.forget_host", "args": {"host": "backup.lan", "port": 22}}, 0)
    assert reply["ok"] is True and reply["result"] is True


def test_the_page_asks_for_it_by_job(client, auth_headers, monkeypatch):
    from backend.services import replication_engine

    jobs = {
        "far": {"id": "far", "target_type": "remote_ssh", "target_host": "backup.lan", "target_port": 2222},
        "near": {"id": "near", "target_type": "local"},
    }
    monkeypatch.setattr(replication_engine.ReplicationEngine, "get_job", lambda self, jid: jobs.get(jid))
    forgot = []
    monkeypatch.setattr(replication_engine, "forget_host", lambda host, port: forgot.append((host, port)) or True)
    url = "/api/storage/replication/jobs/{}/forget-host-key"
    r = client.post(url.format("far"), headers=auth_headers)
    assert r.status_code == 200 and r.json()["forgotten"] is True and forgot == [("backup.lan", 2222)]
    assert client.post(url.format("near"), headers=auth_headers).status_code == 400
    assert client.post(url.format("nope"), headers=auth_headers).status_code == 404

    def refused(host, port):
        raise ValueError("Not forgetting: that is not the name of a machine.")

    monkeypatch.setattr(replication_engine, "forget_host", refused)
    assert client.post(url.format("far"), headers=auth_headers).status_code == 400
