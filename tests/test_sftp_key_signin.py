"""SFTP sign-in with a key: rclone hands over only the key's base64 part, a person pastes the whole line."""

import io
import json
import sys

import pytest

from backend.services import rclone_auth_proxy as proxy

LINE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyDataForTheTestOnly drill@laptop"
BLOB = "AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyDataForTheTestOnly"


def test_the_key_data_is_the_same_however_it_is_written():
    assert proxy.key_data(LINE) == BLOB
    assert proxy.key_data(BLOB) == BLOB  # what rclone sends
    assert proxy.key_data("ssh-ed25519 " + BLOB) == BLOB
    assert proxy.key_data("") == "" and proxy.key_data("   ") == ""
    assert proxy.key_data("ssh-ed25519") == ""  # a type with no key is no key
    assert proxy.key_data("not a key at all") == ""


def test_a_person_signs_in_with_the_key_rclone_hands_over(tmp_path, monkeypatch):
    from backend import config
    from backend.services import login_lockout

    data = tmp_path / "data"
    (data / "sftp").mkdir(parents=True)
    films = tmp_path / "storage" / "docs" / "films"
    films.mkdir(parents=True)
    (data / "sftp" / "users.json").write_text(
        json.dumps([{"username": "drill", "pubkey": LINE, "shares": ["docs/films"]}])
    )
    monkeypatch.setattr(config, "DATA_DIR", str(data))
    monkeypatch.setattr(config, "POOL_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(proxy, "safe_serve_root", lambda path, pool: path)
    monkeypatch.setattr(login_lockout, "remaining", lambda key: 0)
    monkeypatch.setattr(login_lockout, "register_failure", lambda key: None)
    monkeypatch.setattr(login_lockout, "clear", lambda key: None)
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"user": "drill", "public_key": BLOB})))
    monkeypatch.setattr(sys, "stdout", out)
    with pytest.raises(SystemExit) as ok:
        proxy.main()
    assert ok.value.code in (0, None)
    assert json.loads(out.getvalue())["_root"] == str(films)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"user": "drill", "public_key": "AAAAother"})))
    with pytest.raises(SystemExit) as refused:
        proxy.main()
    assert refused.value.code == 1
