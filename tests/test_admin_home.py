"""The first admin's home folder follows the storage folder of the install, not Unraid's path."""

import os

from backend import config, users_db


def test_the_first_admins_home_is_under_this_installs_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "POOL_PATH", "/mnt/storage")
    db = str(tmp_path / "users.db")
    users_db.init_users_db(db)
    admin = users_db.get_user_by_username("admin", db_path=db)
    assert admin["home_directory"] == "/mnt/storage/homes/admin"
    assert users_db._default_home("ana") == "/mnt/storage/homes/ana"  # everyone else is made the same way


def test_an_admin_given_unraids_path_on_another_system_is_moved(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "POOL_PATH", "/mnt/storage")
    db = str(tmp_path / "users.db")
    users_db.init_users_db(db)
    with users_db.users_db_session(db) as conn:
        conn.execute("UPDATE users SET home_directory = ? WHERE username = ?", ("/mnt/user/homes/admin", "admin"))
        conn.execute(
            "INSERT INTO users (id, username, display_name, password_hash, role_id, status, home_directory, created_at, updated_at)"
            " VALUES ('x', 'kim', 'Kim', 'h', 'share_user', 'active', '/mnt/user/homes/somewhere-else', 0, 0)"
        )
    users_db.migrate_legacy_data(db)
    assert users_db.get_user_by_username("admin", db_path=db)["home_directory"] == "/mnt/storage/homes/admin"
    assert users_db.get_user_by_username("kim", db_path=db)["home_directory"] == "/mnt/user/homes/somewhere-else"


def test_unraid_and_an_existing_folder_are_left_alone(tmp_path, monkeypatch):
    db = str(tmp_path / "users.db")
    monkeypatch.setattr(config, "POOL_PATH", "/mnt/user")
    users_db.init_users_db(db)
    with users_db.users_db_session(db) as conn:
        assert users_db._fix_unraid_homes(conn) == 0
    monkeypatch.setattr(config, "POOL_PATH", "/mnt/storage")
    monkeypatch.setattr(os.path, "exists", lambda p: True)  # the Unraid folder is really there
    with users_db.users_db_session(db) as conn:
        assert users_db._fix_unraid_homes(conn) == 0
