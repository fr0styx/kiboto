"""After signing in, the answer says when and from what the account was last signed in."""

from backend import users_db
from backend.services import known_devices

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0.0.0 Safari/537.36"


def test_the_last_good_sign_in_of_this_account_only(tmp_path):
    path = str(tmp_path / "users.db")
    users_db.init_users_db(path)
    assert known_devices.previous_signin("u1", db_path=path) is None
    users_db.log_security_event(
        "auth.login.success", "success", actor_id="u1", actor_ip="192.168.1.20", actor_user_agent=UA, db_path=path
    )
    users_db.log_security_event("auth.login.failure", "failure", actor_id="u1", actor_ip="8.8.8.8", db_path=path)
    users_db.log_security_event("auth.login.success", "success", actor_id="u2", actor_ip="10.0.0.9", db_path=path)
    prev = known_devices.previous_signin("u1", db_path=path)
    assert prev["ip"] == "192.168.1.20" and prev["user_agent"] == UA and prev["at"] > 0
    assert known_devices.previous_signin("nobody", db_path=path) is None


def test_the_sign_in_answer_carries_the_one_before(client):
    first = client.post("/api/auth/login", json={"password": "admin"}, headers={"User-Agent": UA})
    assert first.status_code == 200
    second = client.post("/api/auth/login", json={"password": "admin"}, headers={"User-Agent": "curl/8.5.0"})
    prev = second.json()["previous_signin"]
    assert prev["user_agent"] == UA and prev["at"] > 0  # the one before, not this one


def test_a_log_that_cannot_be_read_does_not_stop_the_sign_in(monkeypatch):
    import sqlite3

    def boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(users_db, "users_db_session", boom)
    assert known_devices.previous_signin("u1") is None
