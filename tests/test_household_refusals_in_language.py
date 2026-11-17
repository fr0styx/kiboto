"""Adding a person and sharing a folder: the refusals a household meets carry their message key."""

import pytest

from backend.errors import SaidError
from backend.services import samba_engine


def test_create_user_says_how(tmp_path):
    from backend import users_db

    with pytest.raises(SaidError) as e:
        users_db.create_user(".hidden", "Hidden", "Long-enough-pass-1")
    assert e.value.text["msg_key"] == "srv.username_unsafe"
    with pytest.raises(SaidError) as e:
        users_db.create_user("a" * 40, "Long", "Long-enough-pass-1")
    assert e.value.text["msg_key"] == "srv.username_length"


def test_share_paths_outside_the_pool_say_where(monkeypatch, tmp_path):
    monkeypatch.setattr(samba_engine, "_allowed_share_roots", lambda: [str(tmp_path)])
    with pytest.raises(SaidError) as e:
        samba_engine.validate_share_path("/etc")
    assert e.value.text == {"msg_key": "srv.share_outside", "params": {"places": str(tmp_path)}}
    monkeypatch.setattr("backend.fsutil.is_protected", lambda p: True)
    (tmp_path / "data").mkdir()
    with pytest.raises(SaidError) as e:
        samba_engine.validate_share_path(str(tmp_path / "data"))
    assert e.value.text["msg_key"] == "srv.share_kiboto_folder"


def test_sharing_a_folder_outside_the_pool_says_where(client, auth_headers, monkeypatch):
    from types import SimpleNamespace

    def refuse(*a, **k):
        raise SaidError("Share path must be inside /mnt/user", "share_outside", places="/mnt/user")

    fake = SimpleNamespace(get_capabilities=lambda: SimpleNamespace(is_observer_mode=False), create_share=refuse)
    monkeypatch.setattr("backend.api.storage.get_storage_platform", lambda: fake)
    r = client.post("/api/storage/shares", json={"name": "photos", "path": "/etc"}, headers=auth_headers)
    body = r.json()
    assert r.status_code == 400 and body["error"] == "invalid_share", body
    assert body["text"] == {"msg_key": "srv.share_outside", "params": {"places": "/mnt/user"}}


def test_a_reserved_share_name_is_refused_with_its_key(tmp_path, monkeypatch):
    monkeypatch.setattr(samba_engine, "validate_share", lambda share: None)
    eng = samba_engine.SambaEngine.__new__(samba_engine.SambaEngine)
    with pytest.raises(SaidError) as e:
        eng.add_or_update_share(samba_engine.SambaShareConfig(name="global", path=str(tmp_path)))
    assert e.value.text["msg_key"] == "srv.share_bad_name"
