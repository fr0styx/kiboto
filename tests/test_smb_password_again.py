"""#71: Samba gets a password only when Kiboto knows it in plain words. One Samba did not take (its
service not up yet) is handed over again at the person's next sign-in."""

import threading

import pytest

from backend import users_db
from backend.services import samba_engine as se


@pytest.fixture
def waiting(tmp_path, monkeypatch):
    monkeypatch.setattr(se, "SMB_WAITING_FILE", str(tmp_path / "smb_waiting.json"))
    monkeypatch.setattr(se, "_serves_files", lambda: True)
    return tmp_path


def test_a_password_samba_did_not_take_is_kept_in_mind_until_it_does(waiting, monkeypatch):
    engine = se.SambaEngine.__new__(se.SambaEngine)
    answers = [False, True]
    monkeypatch.setattr(engine, "_sync_samba_user", lambda username, password=None, delete=False: answers.pop(0))
    assert engine.sync_samba_user("Kim", password="pw-1") is False
    assert se.waiting_for_password("kim") is True
    assert engine.sync_samba_user("kim", password="pw-2") is True
    assert se.waiting_for_password("kim") is False
    se.note_password_handed("ana", False)
    monkeypatch.setattr(engine, "_sync_samba_user", lambda username, password=None, delete=False: False)
    engine.sync_samba_user("ana", delete=True)  # gone from Samba: nothing to wait for
    assert se.waiting_for_password("ana") is False
    monkeypatch.setattr(se, "_serves_files", lambda: False)  # not Kiboto's own Samba: nothing kept
    se.note_password_handed("ben", False)
    assert se.waiting_for_password("ben") is False


def test_the_next_sign_in_hands_the_password_over(client, waiting, monkeypatch):
    user = users_db.create_user("smbkim", "Kim", "a-Long-unique-pw-91", role_id="share_user")
    assert user
    se.note_password_handed("smbkim", False)
    handed = []

    def handed_over(username, password=None, delete=False):
        handed.append((username, password))
        return True

    monkeypatch.setattr(se.get_samba_engine(), "sync_samba_user", handed_over)
    r = client.post("/api/auth/login", json={"username": "smbkim", "password": "a-Long-unique-pw-91"})
    assert r.status_code == 200
    for thread in threading.enumerate():
        if thread.name == "SambaAgain":
            thread.join(5)
    assert handed == [("smbkim", "a-Long-unique-pw-91")]
    handed.clear()
    se.note_password_handed("smbkim", True)
    client.post("/api/auth/login", json={"username": "smbkim", "password": "a-Long-unique-pw-91"})
    assert handed == []  # nothing waits: nothing is handed over
    monkeypatch.undo()
    users_db.delete_user(user["id"])
