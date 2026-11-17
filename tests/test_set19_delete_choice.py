"""Deleting a person asks what happens to their files (Users decision 7 b, SET-19 stage 2)."""

import os
from pathlib import Path

import pytest

from backend import config
from backend.services import user_spaces
from backend.users_db import create_user, get_user_by_username

pytestmark = pytest.mark.real_confirmations


@pytest.fixture
def pool(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "POOL_PATH", str(tmp_path / "pool"))
    monkeypatch.setattr(user_spaces.fs_quota, "mount_for", lambda path, mounts=None: None)
    return tmp_path / "pool"


def _person(name):
    user = get_user_by_username(name) or create_user(name, name.title(), "Some-Pass-12345", role_id="kid")
    home = user_spaces.ensure_home(name)["home"]
    with open(os.path.join(home, "essay.txt"), "w") as f:
        f.write("photosynthesis")
    return user, home


def _token(client, headers, action, target):
    r = client.post("/api/confirmations", json={"action": action, "target": target}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _delete(client, headers, user, action="users.delete", **params):
    tok = _token(client, headers, action, user["id"])
    return client.delete(f"/api/users/{user['id']}", params=params, headers={**headers, "X-Confirm-Token": tok})


def test_kept_files_move_aside_so_the_name_starts_empty(client, auth_headers, pool):
    user, home = _person("del_lea")
    r = _delete(client, auth_headers, user)
    assert r.status_code == 200, r.text
    done = r.json()["files"]
    assert done["files"] == "kept" and os.path.basename(done["where"]).startswith("del_lea-former-")
    assert Path(done["where"], "essay.txt").read_text() == "photosynthesis"
    assert not os.path.exists(home)
    again = create_user("del_lea", "Lea", "Some-Pass-12345", role_id="kid")
    assert os.listdir(user_spaces.ensure_home(again["username"])["home"]) == []


def test_files_given_to_someone_land_in_their_folder(client, auth_headers, pool):
    user, home = _person("del_tom")
    mum, mum_home = _person("del_mum")
    r = _delete(client, auth_headers, user, files="give", give_to="del_mum")
    assert r.status_code == 200, r.text
    done = r.json()["files"]
    assert done == {"files": "given", "to": "del_mum", "where": os.path.join(mum_home, "From del_tom")}
    assert Path(mum_home, "From del_tom", "essay.txt").read_text() == "photosynthesis"
    assert not os.path.exists(home)


def test_deleting_the_files_asks_the_sharper_question(client, auth_headers, pool):
    user, home = _person("del_ben")
    plain = _delete(client, auth_headers, user, files="delete")  # a token for "delete user" only
    assert plain.status_code == 428 and plain.json()["action"] == "users.delete_files"
    assert get_user_by_username("del_ben") and os.path.isdir(home)
    r = _delete(client, auth_headers, user, action="users.delete_files", files="delete")
    assert r.status_code == 200 and r.json()["files"] == {"files": "deleted"}
    assert not os.path.exists(home)


def test_giving_needs_someone_else(client, auth_headers, pool):
    user, home = _person("del_ida")
    assert _delete(client, auth_headers, user, files="give").status_code == 400
    assert _delete(client, auth_headers, user, files="give", give_to="del_ida").status_code == 400
    assert _delete(client, auth_headers, user, files="give", give_to="nobody-here").status_code == 400
    assert _delete(client, auth_headers, user, files="burn").status_code == 422
    assert os.path.isdir(home) and get_user_by_username("del_ida")


def test_nothing_outside_the_homes_folder_is_touched(pool, tmp_path):
    outside = tmp_path / "elsewhere" / "lea"
    outside.mkdir(parents=True)
    assert user_spaces.retire_home("lea", "delete", home=str(outside)) == {"files": "kept", "where": str(outside)}
    assert outside.is_dir()
    assert user_spaces.retire_home("nobody", "keep") == {"files": "none"}
    with pytest.raises(ValueError):
        user_spaces.retire_home("lea", "burn")


def test_a_folder_that_cannot_be_moved_is_reported(client, auth_headers, pool, monkeypatch):
    user, home = _person("del_eva")

    def stuck(src, dest):
        raise OSError("busy")

    monkeypatch.setattr(user_spaces, "_rename", stuck)
    r = _delete(client, auth_headers, user)
    assert r.status_code == 200 and r.json()["files"] == {
        "files": "error",
        "error": "The folder could not be moved or deleted. The server log says why.",
    }
    assert not get_user_by_username("del_eva")  # the account is gone either way
