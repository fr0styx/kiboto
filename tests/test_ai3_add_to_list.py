"""AI finding 18: "Add to list" puts a Hugging Face model on the list; it does not become Kib's model."""

from unittest.mock import patch

from backend.services.media_engine import pull_huggingface_model
from backend.services.rag_engine import get_rag_engine


def _models(cfg):
    return {cfg.get("active_model"), cfg.get("llm_model"), cfg.get("embedding_model")}


def test_adding_a_model_keeps_the_one_in_use(tmp_path):
    with patch("backend.services.rag_engine.RAG_CONFIG_PATH", str(tmp_path / "cfg.json")):
        rag = get_rag_engine()
        before = _models(rag.get_config())
        res = pull_huggingface_model("Qwen/Qwen2.5-3B-Instruct-INT4")
        after = rag.get_config()
        assert res["status"] == "ok" and not res["model"].get("active")
        assert _models(after) == before
        assert any(m.get("hf_repo") == "Qwen/Qwen2.5-3B-Instruct-INT4" for m in after["custom_hf_models"])


def test_adding_a_reader_model_keeps_the_reader_in_use(tmp_path):
    with patch("backend.services.rag_engine.RAG_CONFIG_PATH", str(tmp_path / "cfg.json")):
        rag = get_rag_engine()
        before = rag.get_config().get("embedding_model")
        res = pull_huggingface_model("google/embeddinggemma-300m")
        assert res["model"].get("is_embedding") is True
        assert rag.get_config().get("embedding_model") == before


def test_use_it_still_switches(tmp_path):
    with patch("backend.services.rag_engine.RAG_CONFIG_PATH", str(tmp_path / "cfg.json")):
        res = pull_huggingface_model("Qwen/Qwen2.5-3B-Instruct-INT4", activate=True)
        assert get_rag_engine().get_config()["active_model"] == res["model"]["id"]
