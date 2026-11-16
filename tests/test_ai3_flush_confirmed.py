"""AI finding 28: emptying Kib's index is confirmed on the server, like forgetting one folder."""

import pytest


class _Rag:
    def __init__(self):
        self.flushed = 0

    def flush_index(self):
        self.flushed += 1
        return {"status": "ok"}

    def get_sync_progress(self):
        return {"state": "idle"}

    def get_index_stats(self):
        return {"total_files": 0}


@pytest.fixture
def rag(monkeypatch):
    r = _Rag()
    monkeypatch.setattr("backend.api.media.get_rag_engine", lambda: r)
    return r


@pytest.mark.real_confirmations
@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/ai/index/flush", None),
        ("/api/media/index/flush", None),
        ("/api/ai/index/control", {"action": "flush"}),
        ("/api/ai/index/control", {"action": "clear"}),
    ],
)
def test_emptying_the_index_needs_a_confirmation(client, auth_headers, rag, path, body):
    res = client.post(path, json=body, headers=auth_headers)
    assert res.status_code == 428
    assert res.json()["action"] == "ai.index.flush"
    assert rag.flushed == 0


@pytest.mark.real_confirmations
def test_a_confirmed_flush_runs_once(client, auth_headers, rag):
    tok = client.post(
        "/api/confirmations", json={"action": "ai.index.flush", "target": ""}, headers=auth_headers
    ).json()["token"]
    res = client.post(
        "/api/ai/index/control", json={"action": "flush"}, headers={**auth_headers, "X-Confirm-Token": tok}
    )
    assert res.status_code == 200 and rag.flushed == 1
    again = client.post(
        "/api/ai/index/control", json={"action": "flush"}, headers={**auth_headers, "X-Confirm-Token": tok}
    )
    assert again.status_code == 428 and rag.flushed == 1


@pytest.mark.real_confirmations
def test_pause_needs_no_confirmation(client, auth_headers, rag, monkeypatch):
    monkeypatch.setattr(rag, "pause_sync", lambda: {"status": "ok"}, raising=False)
    assert client.post("/api/ai/index/control", json={"action": "pause"}, headers=auth_headers).status_code == 200
