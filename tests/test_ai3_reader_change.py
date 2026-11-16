"""AI finding 23: a new reader model or index size starts the rebuild instead of a silent switch."""

import pytest


class _Rag:
    def __init__(self):
        self.cfg = {"embedding_model": "embeddinggemma", "embedding_dim": 768, "embedding_host": None, "enabled": True}
        self.saved = []

    def get_config(self):
        return dict(self.cfg)

    def update_config(self, updates):
        self.saved.append(dict(updates))
        self.cfg.update(updates)
        return dict(self.cfg)


@pytest.fixture
def rag(monkeypatch):
    r = _Rag()
    started = []

    async def begin(model, dim, host):
        started.append((model, dim, host))
        return {"status": "started", "model": model or r.cfg["embedding_model"]}

    monkeypatch.setattr("backend.api.media.get_rag_engine", lambda: r)
    monkeypatch.setattr("backend.api.media._begin_reindex", begin)
    r.started = started
    return r


def test_a_new_reader_model_starts_the_rebuild(client, auth_headers, rag):
    res = client.put("/api/ai/config", json={"embedding_model": "bge-m3", "enabled": True}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["reindex"]["status"] == "started"
    assert rag.started == [("bge-m3", None, None)]
    # the setting itself switches when the rebuild is done, not now
    assert rag.cfg["embedding_model"] == "embeddinggemma"
    assert rag.saved == [{"enabled": True}]


def test_a_new_index_size_too(client, auth_headers, rag):
    res = client.post("/api/ai/config", json={"embedding_dim": 256}, headers=auth_headers)
    assert res.json()["reindex"]["status"] == "started" and rag.started == [(None, 256, None)]
    assert rag.saved == []


def test_the_same_values_change_nothing(client, auth_headers, rag):
    res = client.put(
        "/api/ai/config", json={"embedding_model": "embeddinggemma", "embedding_dim": 768}, headers=auth_headers
    )
    assert res.status_code == 200 and "reindex" not in res.json()
    assert rag.started == []


def test_other_settings_save_as_before(client, auth_headers, rag):
    res = client.put("/api/ai/config", json={"enabled": False}, headers=auth_headers)
    assert res.json()["enabled"] is False and "reindex" not in res.json() and rag.started == []
