"""AI 3: reading progress has a total, from what the index knew of the folders (no drive is read)."""

import time
from unittest.mock import patch

from backend.services.rag_engine import RagSearchEngine


def test_the_total_is_what_the_index_knows(tmp_path):
    with patch("backend.services.rag_engine.RAG_CONFIG_PATH", str(tmp_path / "cfg.json")):
        engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
        docs = tmp_path / "docs"
        (docs / "sub").mkdir(parents=True)
        for i in range(3):
            (docs / f"n{i}.md").write_text(f"# Note {i}\\nKiboto test text {i}.\\n")
        (docs / "sub" / "deep.md").write_text("# Deep\\nMore text.\\n")
        other = tmp_path / "docsx"  # a name that starts like docs but is another folder
        other.mkdir()
        (other / "x.md").write_text("# X\\nText.\\n")
        engine.index_directory(str(docs), respect_standby=False)
        engine.index_directory(str(other), respect_standby=False)
        assert engine.known_files_under([str(docs)]) == 4
        assert engine.known_files_under([str(docs), str(other)]) == 5
        assert engine.known_files_under([str(tmp_path / "nothing")]) == 0
        # a new run starts with that total in its progress
        engine.index_paths([str(docs)], respect_standby=False)
        assert engine.get_sync_progress().get("total_files") == 4


def test_no_index_no_total(tmp_path, monkeypatch):
    with patch("backend.services.rag_engine.RAG_CONFIG_PATH", str(tmp_path / "cfg.json")):
        engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))

        def broken(*a, **k):
            raise OSError("the index file cannot be opened")

        monkeypatch.setattr(engine, "_get_conn", broken)
        assert engine.known_files_under(["/mnt/user/docs"]) == 0
