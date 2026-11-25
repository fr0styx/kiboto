"""The first sign-in on a machine set up for Kiboto: a code shown on the machine itself.

The first-time password is in a file only root can read. On a box with no screen and no keyboard
nobody reads it, so nobody could take the box into use."""

import os
import re

import pytest

from backend import config, first_run, runtime, users_db


def _text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def machine(monkeypatch, tmp_path):
    """A managed host whose notices and first-password file are in tmp_path."""
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    monkeypatch.setattr(first_run, "ISSUE", str(tmp_path / "etc" / "issue.d" / "kiboto.issue"))
    monkeypatch.setattr(first_run, "MOTD", str(tmp_path / "etc" / "motd.d" / "kiboto"))
    monkeypatch.setattr(config, "initial_password_file", lambda: str(tmp_path / "data" / "initial-admin-password"))
    return tmp_path


def test_a_code_can_be_typed():
    code = first_run.new_code()
    assert re.fullmatch(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", code)
    assert not set(code) & set("IO01")
    assert first_run.new_code() != code


@pytest.mark.parametrize(
    "typed, means",
    [
        ("abcd-efgh-jkmn", "ABCD-EFGH-JKMN"),
        ("ABCDEFGHJKMN", "ABCD-EFGH-JKMN"),
        (" abcd efgh jkmn ", "ABCD-EFGH-JKMN"),
        ("ABCD-EFGH-JKMN", "ABCD-EFGH-JKMN"),
        ("my own long password", "my own long password"),  # not a code: left exactly as typed
        ("ABCD-EFGH-JKM0", "ABCD-EFGH-JKM0"),  # a character no code has
        ("ABCD-EFGH", "ABCD-EFGH"),
    ],
)
def test_what_was_typed_is_read_as_a_code_is_written(typed, means):
    assert first_run.tidy(typed) == means


def _waiting(code):
    """The code file the door reads (users_db writes it before showing the code)."""
    os.makedirs(os.path.dirname(config.initial_password_file()), exist_ok=True)
    with open(config.initial_password_file(), "w", encoding="utf-8") as f:
        f.write(code + "\n")


def test_the_machine_shows_the_code_until_a_password_is_chosen(machine):
    _waiting("ABCD-EFGH-JKMN")
    assert first_run.show("ABCD-EFGH-JKMN") is True
    issue = _text(first_run.ISSUE)
    assert "ABCD-EFGH-JKMN" in issue and "http://\\4:8082" in issue  # \4: the console writes the address there
    motd = _text(first_run.MOTD)
    assert "ABCD-EFGH-JKMN" in motd and "\\4" not in motd
    first_run.clear()
    assert not os.path.exists(first_run.ISSUE) and not os.path.exists(first_run.MOTD)
    first_run.clear()  # twice is fine


def test_at_start_the_notice_follows_the_waiting_first_sign_in(machine):
    first_run.refresh()
    assert not os.path.exists(first_run.ISSUE)  # nothing waiting: nothing shown
    os.makedirs(os.path.dirname(config.initial_password_file()))
    with open(config.initial_password_file(), "w", encoding="utf-8") as f:
        f.write("ABCD-EFGH-JKMN\n")
    assert first_run.waiting() is True
    first_run.refresh()
    assert "ABCD-EFGH-JKMN" in _text(first_run.ISSUE)
    os.remove(config.initial_password_file())
    first_run.refresh()
    assert not os.path.exists(first_run.ISSUE) and first_run.waiting() is False


def test_another_machine_shows_nothing(machine, monkeypatch):
    monkeypatch.setattr(runtime, "managed_host", lambda: False)
    assert first_run.show("ABCD-EFGH-JKMN") is False and first_run.where() == "file"
    first_run.refresh()
    first_run.clear()
    assert not os.path.exists(first_run.ISSUE) and not os.path.exists(first_run.MOTD)


def test_a_notice_that_cannot_be_written_does_not_stop_the_start(machine, monkeypatch):
    blocked = machine / "a-file"
    blocked.write_text("")
    monkeypatch.setattr(first_run, "ISSUE", str(blocked / "kiboto.issue"))
    _waiting("ABCD-EFGH-JKMN")
    assert first_run.show("ABCD-EFGH-JKMN") is True  # the other notice is still written
    assert os.path.exists(first_run.MOTD)


def test_the_first_password_is_a_code_on_a_managed_host_and_goes_with_its_notice(machine, monkeypatch):
    assert first_run.where() == "machine"
    code = users_db._first_time_password()
    assert re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}", code)
    assert code in _text(first_run.ISSUE)
    os.remove(first_run.ISSUE)
    assert users_db._first_time_password() == code  # a second start: the same code, shown again
    assert code in _text(first_run.ISSUE)
    users_db._forget_first_time_password()
    assert not os.path.exists(first_run.ISSUE) and not os.path.exists(config.initial_password_file())
    monkeypatch.setattr(runtime, "managed_host", lambda: False)
    other = users_db._first_time_password()  # in a container: the long password in its file, as before
    assert len(other) >= 20 and not os.path.exists(first_run.ISSUE)


def test_the_sign_in_page_is_told_where_to_look_without_signing_in(client, machine):
    assert client.get("/api/auth/first-run").json() == {"waiting": False, "where": "machine"}
    os.makedirs(os.path.dirname(config.initial_password_file()))
    with open(config.initial_password_file(), "w", encoding="utf-8") as f:
        f.write("ABCD-EFGH-JKMN\n")
    assert client.get("/api/v1/auth/first-run").json() == {"waiting": True, "where": "machine"}


def test_the_code_signs_in_however_it_is_typed_and_only_while_waiting(client, machine):
    users_db.create_user("firstadmin", "First", "ABCD-EFGH-JKMN", role_id="superadmin", must_change_password=True)
    typed = {"username": "firstadmin", "password": "abcd efgh jkmn"}
    assert client.post("/api/auth/login", json=typed).status_code == 401  # nobody is waiting for a code
    os.makedirs(os.path.dirname(config.initial_password_file()))
    with open(config.initial_password_file(), "w", encoding="utf-8") as f:
        f.write("ABCD-EFGH-JKMN\n")
    r = client.post("/api/auth/login", json=typed)
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    assert (
        client.post("/api/auth/login", json={"username": "firstadmin", "password": "abcd-efgh-jkmx"}).status_code == 401
    )


def test_only_root_reads_the_code_on_the_machine(machine):
    os.makedirs(os.path.dirname(first_run.ISSUE), exist_ok=True)
    with open(first_run.ISSUE, "w", encoding="utf-8") as f:
        f.write("old")
    os.chmod(first_run.ISSUE, 0o644)
    _waiting("ABCD-EFGH-JKMN")
    assert first_run.show("ABCD-EFGH-JKMN") is True
    for path in (first_run.ISSUE, first_run.MOTD):
        assert os.stat(path).st_mode & 0o777 == 0o600
        assert "ABCD-EFGH-JKMN" in _text(path)
