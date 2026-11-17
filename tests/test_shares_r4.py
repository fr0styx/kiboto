"""Shares R4 (owner, 16 Nov 2026 evening): one access list. A share's own Samba lists are folded into
the share access table, the old lists are copied aside first, and what each person could do stays."""

import json

import pytest

from backend import config
from backend.services import share_access as sa
from backend.services.samba_engine import SambaShareConfig


class Engine:
    def __init__(self, shares):
        self.shares = {s.name: s for s in shares}
        self.saved = []

    def list_shares(self):
        return list(self.shares.values())

    def add_or_update_share(self, share):
        self.saved.append(share.name)
        self.shares[share.name] = share
        return share


PEOPLE = [
    {"username": "anna", "role_id": "family_member", "status": "active"},
    {"username": "ben", "role_id": "family_member", "status": "active"},
    {"username": "carl", "role_id": "kid", "status": "active"},
    {"username": "dora", "role_id": "family_member", "status": "active"},
    {"username": "eve", "role_id": "family_member", "status": "disabled"},
    {"username": "owner", "role_id": "superadmin", "status": "active"},
]


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    refreshed = []
    monkeypatch.setattr("backend.services.samba_engine.refresh_access", lambda: refreshed.append(1))
    sa.save_config({"default_level": "none", "shares": {"media": {"users": {"carl": "none"}}}})
    return tmp_path, refreshed


def _engine():
    return Engine(
        [
            SambaShareConfig(name="media", path="/mnt/storage/media", valid_users="anna ben carl", read_list="ben"),
            SambaShareConfig(name="family", path="/mnt/storage/family", valid_users="@family"),
            SambaShareConfig(name="open", path="/mnt/storage/open"),
        ]
    )


def test_the_lists_join_the_table_and_everyone_keeps_what_they_had(data):
    tmp, refreshed = data
    engine = _engine()
    res = sa.fold_share_lists(engine, PEOPLE)
    assert res["folded"] == ["media"]
    assert res["kept"] == [{"name": "family", "why": "groups"}]
    users = sa.load_config()["shares"]["media"]["users"]
    # anna was on the list (and may change files), ben was on the read list,
    # carl's own cell already decided Files and stays, dora was not on the list ("none" anyway),
    # eve is disabled and the owner opens every folder
    assert users == {"anna": "write", "ben": "read", "carl": "none"}
    assert res["changed"] == {"media": {"anna": "write", "ben": "read"}}
    media = engine.shares["media"]
    assert media.valid_users is None and media.read_list is None and media.write_list is None
    assert engine.shares["family"].valid_users == "@family"  # groups cannot be said person by person
    assert engine.saved == ["media"] and refreshed == [1]
    before = json.loads((tmp / "share_lists_before_fold.json").read_text())
    assert before["media"]["valid_users"] == "anna ben carl" and before["media"]["read_list"] == "ben"
    assert "family" not in before


def test_folding_again_changes_nothing(data):
    engine = _engine()
    sa.fold_share_lists(engine, PEOPLE)
    engine.saved.clear()
    res = sa.fold_share_lists(engine, PEOPLE)
    assert res == {"folded": [], "kept": [{"name": "family", "why": "groups"}], "changed": {}}
    assert engine.saved == []


def test_a_read_only_share_gives_read(data):
    engine = Engine([SambaShareConfig(name="docs", path="/mnt/storage/docs", read_only=True, valid_users="anna")])
    sa.fold_share_lists(engine, PEOPLE)
    assert sa.load_config()["shares"]["docs"]["users"] == {"anna": "read"}


def test_people_chosen_when_a_share_is_made_go_into_the_table(data):
    sa.grant_many("photos", {"Anna": "write", "ben": "read"})
    assert sa.load_config()["shares"]["photos"]["users"] == {"anna": "write", "ben": "read"}
