"""Who can really open each shared folder (SET-22, Shares 2)."""

import pytest

from backend.services import share_access as sa

SHARES = [
    {"name": "photos", "path": "/mnt/pool/photos", "samba": None},
    {
        "name": "media",
        "path": "/mnt/pool/media",
        "samba": {"valid": {"ben"}, "read": set(), "write": set(), "read_only": False},
    },
]
PEOPLE = [
    {"username": "owner", "display_name": "Owner", "role_id": "superadmin", "status": "active"},
    {"username": "anna", "display_name": "Anna", "role_id": "share_user", "status": "active"},
    {"username": "ben", "display_name": "Ben", "role_id": "share_user", "status": "active"},
    {"username": "mia", "display_name": "Mia", "role_id": "kid", "status": "active"},
    {"username": "old", "display_name": "Old", "role_id": "share_user", "status": "disabled"},
]


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(sa, "known_shares", lambda: SHARES)
    cfg = {
        "default_level": "none",
        "role_defaults": {"kid": "read"},
        "shares": {"photos": {"users": {"anna": "write"}}},
    }
    monkeypatch.setattr(sa, "load_config", lambda: cfg)


def test_each_person_level_with_administrators_and_role_defaults(setup):
    who = sa.who_can_open(PEOPLE, "zettos")
    assert who["host"] == ""
    photos = {p["username"]: p["level"] for p in who["shares"][0]["people"]}
    assert photos == {"owner": "write", "anna": "write", "ben": "none", "mia": "read"}
    media = {p["username"]: p["level"] for p in who["shares"][1]["people"]}
    assert media["ben"] == "write" and media["anna"] == "none" and media["owner"] == "write"  # Samba's list
    assert who["shares"][0]["people"][0]["admin"] is True


def test_turned_off_people_are_left_out_and_the_host_is_named(setup):
    who = sa.who_can_open(PEOPLE, "unraid")
    assert who["host"] == "unraid"
    assert "old" not in {p["username"] for p in who["shares"][0]["people"]}


def test_the_route_answers(client, auth_headers, setup):
    r = client.get("/api/storage/share-access/who", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert {s["name"] for s in r.json()["shares"]} == {"photos", "media"}
