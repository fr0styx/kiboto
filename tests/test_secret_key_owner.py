"""secret.key made by root in another user's data folder belongs to that user (fresh install, step 9)."""

import os
import types

from backend import config


def test_root_hands_the_key_to_the_folder_owner(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(config.os, "geteuid", lambda: 0)
    monkeypatch.setattr(config.os, "stat", lambda p: types.SimpleNamespace(st_uid=999, st_gid=987))
    monkeypatch.setattr(config.os, "chown", lambda p, u, g: calls.append((p, u, g)))
    config._hand_to_folder_owner(str(tmp_path / "secret.key"), str(tmp_path))
    assert calls == [(str(tmp_path / "secret.key"), 999, 987)]


def test_a_root_owned_folder_or_a_non_root_process_changes_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(config.os, "chown", lambda p, u, g: calls.append((p, u, g)))
    monkeypatch.setattr(config.os, "geteuid", lambda: 0)
    monkeypatch.setattr(config.os, "stat", lambda p: types.SimpleNamespace(st_uid=0, st_gid=0))
    config._hand_to_folder_owner("x", "y")
    monkeypatch.setattr(config.os, "geteuid", lambda: 999)
    config._hand_to_folder_owner("x", "y")
    assert calls == []


def test_the_key_is_written_through_it(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "SECRET_KEY_FILE", str(tmp_path / "secret.key"))
    monkeypatch.setattr(
        config,
        "_hand_to_folder_owner",
        lambda path, folder: seen.append((os.path.basename(path).split(".tmp-")[0], folder)),
    )
    config._persist_key("k" * 64, replace=False)
    assert seen == [("secret.key", str(tmp_path))]
    assert (tmp_path / "secret.key").read_text() == "k" * 64
