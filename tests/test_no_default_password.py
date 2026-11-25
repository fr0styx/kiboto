"""No shared default admin password anywhere (UK PSTI; audit review Batch 0)."""

import os

from backend import config


def test_empty_web_password_means_no_stored_hash():
    assert config.initial_password_hash("") == ""
    assert config.initial_password_hash("Chosen-Pass-1") != ""


def test_docs_and_templates_do_not_publish_admin_admin():
    root = os.path.join(os.path.dirname(__file__), "..")
    for rel in (
        "README.md",
        "docs/INSTALLATION.md",
        "unraid/kiboto.xml",
        "docker-compose.yml",
        ".env.example",
    ):
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            text = f.read()
        assert "Password `admin`" not in text, rel
        assert "WEB_PASSWORD=admin" not in text and "WEB_PASSWORD:-admin" not in text, rel


def test_only_a_literal_admin_counts_as_admin(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "STORED_PASSWORD_HASH", config.hash_password("Chosen-Pass-1"))
    (tmp_path / "initial-admin-password").write_text("x")
    config._default_pw_cache["hash"] = None
    assert config.is_using_default_password() is True
    assert config.password_is_admin() is False
    monkeypatch.setattr(config, "STORED_PASSWORD_HASH", config.hash_password("admin"))
    assert config.password_is_admin() is True
