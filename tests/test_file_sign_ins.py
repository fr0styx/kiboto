"""SFTP and WebDAV forget what rclone kept of a sign-in once the person's sign-in changes. rclone
keeps a sign-in for minutes, keyed on the name: tried on Kiboto OS, after a password change SFTP
still took the old password and refused the new one."""

import threading

import pytest

from backend import users_db
from backend.errors import SaidError
from backend.services import file_sign_ins, sftp_engine, webdav_engine


class Server:
    def __init__(self, on=True, fails=None):
        self.on, self.fails, self.restarted = on, fails, 0

    def forget_sign_ins(self):
        if self.fails:
            raise self.fails
        self.restarted += int(self.on)
        return self.on


def test_the_servers_that_are_on_start_again_and_a_refusal_is_only_noted(monkeypatch):
    sftp, dav = Server(), Server()
    monkeypatch.setattr(sftp_engine, "get_sftp_engine", lambda: sftp)
    monkeypatch.setattr(webdav_engine, "get_webdav_engine", lambda: dav)
    assert file_sign_ins.again() == ["sftp", "webdav"] and sftp.restarted == dav.restarted == 1
    monkeypatch.setattr(sftp_engine, "get_sftp_engine", lambda: Server(on=False))
    monkeypatch.setattr(webdav_engine, "get_webdav_engine", lambda: Server(fails=OSError("busy")))
    assert file_sign_ins.again() == []
    monkeypatch.setattr(sftp_engine, "get_sftp_engine", lambda: Server(fails=SaidError("not here", "not_on_kiboto_os")))
    assert file_sign_ins.again() == []

    ran = []
    monkeypatch.setattr(file_sign_ins, "again", lambda: ran.append(1))
    file_sign_ins.forget("kim")
    for thread in threading.enumerate():
        if thread.name == "FileSignInsForget":
            thread.join(5)
    assert ran == [1]


@pytest.mark.parametrize("which", ["sftp", "webdav"])
def test_forgetting_starts_only_a_server_that_is_on_and_keeps_its_setting(monkeypatch, which):
    """The restart that forgets sign-ins once raced with "turn SFTP off" and switched it back on."""
    engine = sftp_engine.SFTPEngine() if which == "sftp" else webdav_engine.WebdavEngine()
    state = {"enabled": True, "running": True}
    did = []
    if which == "sftp":
        monkeypatch.setattr(engine, "get_config", lambda: {"enabled": state["enabled"]})
        monkeypatch.setattr(engine, "get_status", lambda: type("S", (), {"running": state["running"]})())
    else:
        monkeypatch.setattr(engine, "load_config", lambda: {"enabled": state["enabled"]})
        monkeypatch.setattr(engine, "is_running", lambda: state["running"])
    monkeypatch.setattr(engine, "_stop", lambda: did.append("stop"))
    monkeypatch.setattr(engine, "_start", lambda: did.append("start"))
    assert engine.forget_sign_ins() is True and did == ["stop", "start"]
    state["enabled"] = False
    assert engine.forget_sign_ins() is False
    state.update(enabled=True, running=False)
    assert engine.forget_sign_ins() is False and did == ["stop", "start"]
    engine.stop()
    engine.start()
    assert did == ["stop", "start", "stop", "start"]


def test_removing_an_sftp_account_forgets_its_sign_in(monkeypatch, tmp_path):
    engine = sftp_engine.SFTPEngine()
    monkeypatch.setattr(sftp_engine, "SFTP_USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setattr(engine, "list_users", lambda mask_passwords=True: [{"username": "cam"}, {"username": "dee"}])
    monkeypatch.setattr(engine, "get_config", lambda: {"enabled": True})
    forgot = []
    monkeypatch.setattr(engine, "forget_sign_ins", lambda: forgot.append(1) or True)
    assert engine.delete_user("cam") is True
    for thread in threading.enumerate():
        if thread.name == "SftpForget":
            thread.join(5)
    assert forgot == [1] and engine.delete_user("nobody") is False


@pytest.fixture
def heard(monkeypatch):
    said = []
    monkeypatch.setattr(users_db, "_SIGN_IN_HOOKS", [])
    users_db.on_sign_in_change(said.append)
    users_db.on_sign_in_change(said.append)  # once only
    return said


def test_a_new_password_a_second_step_and_removal_are_heard(tmp_path, heard, monkeypatch):
    db = str(tmp_path / "users.db")
    users_db.init_users_db(db)
    user = users_db.create_user("kim", "Kim", "a-Long-unique-pw-91", role_id="share_user", db_path=db)
    assert users_db.update_user_password(user["id"], "another-Long-pw-27", db_path=db)
    assert heard == ["kim"]
    assert users_db.enable_user_mfa(user["id"], "JBSWY3DPEHPK3PXP", [], db_path=db)
    assert heard == ["kim", "kim"]
    monkeypatch.setattr(users_db, "refresh_access", lambda: None, raising=False)
    import backend.services.samba_engine as samba

    monkeypatch.setattr(samba, "refresh_access", lambda: None)
    assert users_db.delete_user(user["id"], db_path=db)
    assert heard == ["kim", "kim", "kim"]


def test_a_person_turned_off_is_heard_and_a_hook_that_fails_is_only_noted(heard, monkeypatch):
    monkeypatch.setattr(users_db, "get_user_by_id", lambda uid, db_path=None: {"username": "ana"})
    import backend.services.samba_engine as samba

    monkeypatch.setattr(samba.get_samba_engine(), "set_account_enabled", lambda name, active: None)

    def broken(name):
        raise RuntimeError("no")

    users_db.on_sign_in_change(broken)
    users_db._network_follows_status("u1", False)
    assert heard == ["ana"]
