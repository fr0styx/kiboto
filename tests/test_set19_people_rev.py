"""The People lists update themselves: people_rev goes up on every change (SET-19)."""

from backend import users_db


def test_people_and_sign_ins_move_the_count(monkeypatch):
    monkeypatch.setattr("backend.services.samba_engine.refresh_access", lambda: None)
    start = users_db.people_rev()
    user = users_db.create_user("rev_ida", "Ida", "Some-Pass-12345", role_id="kid")
    after_add = users_db.people_rev()
    assert after_add > start
    users_db.update_user_profile(user["id"], status="disabled")
    assert users_db.people_rev() > after_add
    users_db.update_user_profile(user["id"], status="active")
    before = users_db.people_rev()
    users_db.create_user_session(user["id"], user["username"])
    assert users_db.people_rev() > before
    before = users_db.people_rev()
    users_db.revoke_all_sessions_for_user(user["id"])
    assert users_db.people_rev() > before
    before = users_db.people_rev()
    users_db.delete_user(user["id"])
    assert users_db.people_rev() > before


def test_the_live_stats_carry_it():
    from backend.services import stats_collector

    assert stats_collector._people_rev() == users_db.people_rev()
