"""A person added by an administrator chooses their own password at first sign-in (SET-19)."""

from backend.users_db import get_user_by_username


def test_the_new_person_is_asked_and_the_flag_goes_with_their_new_password(client, auth_headers):
    r = client.post(
        "/api/users",
        json={"username": "own_zoe", "password": "First-Pass-12345", "role_id": "kid", "must_change_password": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    login = client.post("/api/auth/login", json={"username": "own_zoe", "password": "First-Pass-12345"}).json()
    assert login["choose_own_password"] is True
    headers = {"Authorization": f"Bearer {login['token']}"}
    uid = get_user_by_username("own_zoe")["id"]
    changed = client.post(
        f"/api/users/{uid}/password",
        json={"current_password": "First-Pass-12345", "new_password": "Zoes-Own-Pass-987"},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text
    again = client.post("/api/auth/login", json={"username": "own_zoe", "password": "Zoes-Own-Pass-987"}).json()
    assert again["choose_own_password"] is False


def test_without_the_box_ticked_nothing_is_asked(client, auth_headers):
    r = client.post(
        "/api/users",
        json={"username": "own_max", "password": "First-Pass-12345", "role_id": "kid"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    login = client.post("/api/auth/login", json={"username": "own_max", "password": "First-Pass-12345"}).json()
    assert login["choose_own_password"] is False
