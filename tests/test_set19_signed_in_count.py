"""People rows say on how many devices each person is signed in (SET-19)."""

from backend import users_db


def test_the_list_counts_live_sign_ins():
    user = users_db.get_user_by_username("cnt_ola") or users_db.create_user(
        "cnt_ola", "Ola", "Some-Pass-12345", role_id="kid"
    )
    users_db.revoke_all_sessions_for_user(user["id"])
    row = next(u for u in users_db.list_users() if u["id"] == user["id"])
    assert row["signed_in"] == 0
    users_db.create_user_session(user["id"], user["username"])
    users_db.create_user_session(user["id"], user["username"])
    row = next(u for u in users_db.list_users() if u["id"] == user["id"])
    assert row["signed_in"] == 2
