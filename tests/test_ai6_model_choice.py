"""AI decision 6: Kib answers with Automatic (recommended), Fast, Balanced or Best, and keeps the choice."""

from backend.services import model_benchmark as mb


def _r(name, tps, size):
    return {"name": name, "ok": True, "tokens_per_s": tps, "size_bytes": size}


def test_best_is_the_largest_usable_model():
    rec = mb.recommend([_r("small", 45, 2), _r("mid", 18, 8), _r("big", 5, 40), _r("huge", 1.5, 70)])
    assert rec == {"fast": "small", "balanced": "mid", "best": "big"}
    assert mb.recommend([_r("slow", 2, 9)]) == {"fast": "slow", "balanced": "slow", "best": "slow"}
    assert mb.recommend([{"name": "x", "ok": False}]) == {"fast": None, "balanced": None, "best": None}


def test_a_choice_stands_for_a_model():
    rec = {"fast": "small", "balanced": "mid", "best": "big"}
    assert [mb.model_for(c, rec) for c in ("auto", "fast", "balanced", "best", "manual")] == [
        "mid",
        "small",
        "mid",
        "big",
        None,
    ]
    assert mb.model_for("auto", {}) is None


def test_after_a_speed_test_the_choice_follows_but_a_named_model_stays():
    rec = {"fast": "small", "balanced": "mid", "best": "big"}
    saved = {}
    assert mb.follow_choice(saved.update, {"model_choice": "best", "active_model": "mid"}, rec) == "big"
    assert saved == {"active_model": "big"}
    assert mb.follow_choice(saved.update, {"active_model": "mid"}, rec) is None  # Automatic already on Balanced's model
    assert mb.follow_choice(saved.update, {"model_choice": "manual", "active_model": "mine"}, rec) is None


def test_the_route_keeps_the_choice(client, auth_headers, monkeypatch):
    from backend.services import rag_engine

    cfg = {"active_model": "old", "model_choice": "manual"}
    monkeypatch.setattr(rag_engine.get_rag_engine(), "update_config", lambda u: cfg.update(u) or dict(cfg))
    monkeypatch.setattr(mb, "load_results", lambda: {"recommended": {}})
    r = client.post("/api/ai/models/benchmark/apply", json={"tier": "auto"}, headers=auth_headers)
    assert r.status_code == 200 and cfg == {
        "active_model": "old",
        "model_choice": "auto",
    }  # Automatic works before a test
    assert client.post("/api/ai/models/benchmark/apply", json={"tier": "best"}, headers=auth_headers).status_code == 409
    monkeypatch.setattr(mb, "load_results", lambda: {"recommended": {"fast": "s", "balanced": "m", "best": "b"}})
    r = client.post("/api/ai/models/benchmark/apply", json={"tier": "best"}, headers=auth_headers)
    assert r.json() == {"active_model": "b", "tier": "best", "model_choice": "best"}
    assert client.post("/api/ai/models/benchmark/apply", json={"tier": "huge"}, headers=auth_headers).status_code == 422


def test_the_background_test_follows_the_choice(monkeypatch):
    from backend.services import rag_engine

    cfg = {"active_model": "old", "model_choice": "fast"}
    rag = rag_engine.get_rag_engine()
    monkeypatch.setattr(rag, "get_config", lambda: dict(cfg))
    monkeypatch.setattr(rag, "update_config", lambda u: cfg.update(u) or dict(cfg))
    monkeypatch.setattr(mb, "run", lambda: {"recommended": {"fast": "quick"}})

    class _Now:
        def __init__(self, target, name, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(mb.threading, "Thread", _Now)
    mb._job.clear()
    assert mb.start() == {"started": True}
    assert cfg["active_model"] == "quick"
