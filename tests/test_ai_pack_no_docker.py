"""The AI pack's status says when Docker can't be reached, instead of answering 500."""

import pytest

from backend.services import ai_pack


def test_no_docker_is_a_state(monkeypatch):
    def gone(*a, **k):
        raise RuntimeError("Docker socket not reachable: Docker socket /var/run/docker.sock not found")

    monkeypatch.setattr(ai_pack, "_docker", gone)
    out = ai_pack.status({})
    assert out["state"] == "no-docker" and out["installed"] is False and "recommendation" in out


def test_other_failures_still_raise(monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("something else")

    monkeypatch.setattr(ai_pack, "_docker", broken)
    with pytest.raises(RuntimeError, match="something else"):
        ai_pack.status({})


def test_the_route_answers(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        ai_pack, "_docker", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Docker socket not reachable: x"))
    )
    r = client.get("/api/ai/pack", headers=auth_headers)
    assert r.status_code == 200 and r.json()["state"] == "no-docker"
