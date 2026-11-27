"""The folder holding a share's encrypted files is never reached through a link."""

import os

import pytest

from backend import legacy_names
from backend.services import encrypted_folders as ef


def test_a_plain_hidden_folder_is_used(tmp_path):
    share = tmp_path / "docs"
    (share / ef.HIDDEN).mkdir(parents=True)
    assert ef.cipher_path(str(share), "tax") == str(share / ef.HIDDEN / "tax")


def test_a_missing_hidden_folder_is_fine(tmp_path):
    share = tmp_path / "docs"
    share.mkdir()
    assert ef.cipher_path(str(share), "tax") == str(share / ef.HIDDEN / "tax")


def test_a_share_reached_through_a_link_is_fine(tmp_path):
    real = tmp_path / "pool" / "docs"
    (real / ef.HIDDEN).mkdir(parents=True)
    os.symlink(real, tmp_path / "docs")
    assert ef.cipher_path(str(tmp_path / "docs"), "tax") == str(tmp_path / "docs" / ef.HIDDEN / "tax")


def test_a_hidden_folder_that_is_a_link_is_refused(tmp_path):
    share = tmp_path / "docs"
    share.mkdir()
    elsewhere = tmp_path / "etc"
    elsewhere.mkdir()
    os.symlink(elsewhere, share / ef.HIDDEN)
    with pytest.raises(ValueError, match="link"):
        ef.cipher_path(str(share), "tax")


def test_a_folder_inside_that_is_a_link_is_refused(tmp_path):
    share = tmp_path / "docs"
    (share / ef.HIDDEN).mkdir(parents=True)
    os.symlink(tmp_path, share / ef.HIDDEN / "tax")
    with pytest.raises(ValueError, match="link"):
        ef.cipher_path(str(share), "tax")


def test_an_old_hidden_folder_that_is_a_link_is_not_renamed(tmp_path, monkeypatch):
    share = tmp_path / "docs"
    share.mkdir()
    elsewhere = tmp_path / "etc"
    elsewhere.mkdir()
    os.symlink(elsewhere, share / legacy_names.OLD_ENCRYPTED_HIDDEN)
    monkeypatch.setattr(ef, "_mounted", lambda: set())
    monkeypatch.setattr(ef.ei, "folders", lambda: {"tax": {"share": "docs"}})
    monkeypatch.setattr(ef, "_share_path", lambda share_name: str(share))
    assert ef.rename_hidden_folders() == 0
    assert os.path.islink(share / legacy_names.OLD_ENCRYPTED_HIDDEN)
    assert not os.path.lexists(share / ef.HIDDEN)


def test_an_old_hidden_folder_is_renamed(tmp_path, monkeypatch):
    share = tmp_path / "docs"
    (share / legacy_names.OLD_ENCRYPTED_HIDDEN / "tax").mkdir(parents=True)
    monkeypatch.setattr(ef, "_mounted", lambda: set())
    monkeypatch.setattr(ef.ei, "folders", lambda: {"tax": {"share": "docs"}})
    monkeypatch.setattr(ef, "_share_path", lambda share_name: str(share))
    assert ef.rename_hidden_folders() == 1
    assert (share / ef.HIDDEN / "tax").is_dir()
