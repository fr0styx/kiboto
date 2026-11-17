"""Whole-app refusals carry their message key, so the Apps window says them in the reader's language."""

import pytest

from backend.services import docker_stacks as ds


@pytest.fixture
def no_app(monkeypatch):
    monkeypatch.setattr(ds, "get_stack_details", lambda name: {"containers": []})


def test_update_and_backup_of_a_missing_app(client, auth_headers, no_app):
    for path in ("/api/docker/stacks/ghost/update", "/api/docker/stacks/ghost/backup"):
        r = client.post(path, headers=auth_headers)
        body = r.json()
        assert r.status_code == 400 and body["error"] == "app_refused", (path, body)
        assert body["text"] == {"msg_key": "srv.app_not_found", "params": {"name": "ghost"}}


def test_kiboto_itself_is_refused_with_its_key(monkeypatch):
    from backend.errors import SaidError

    monkeypatch.setattr(ds, "get_stack_details", lambda name: {"containers": [{"id": "abc", "name": "kiboto"}]})
    monkeypatch.setattr(ds, "is_kiboto_itself", lambda cid, name: True)
    with pytest.raises(SaidError) as e:
        ds.app_details("kiboto")
    assert e.value.text["msg_key"] == "srv.app_is_kiboto"


def test_a_failed_backup_keeps_the_app_and_says_why(client, auth_headers, monkeypatch):
    from backend.services import whole_app

    def boom(name, keep_backup=True):
        raise OSError("disk full")

    monkeypatch.setattr(whole_app, "remove_app", boom)
    r = client.delete("/api/docker/stacks/shop", headers=auth_headers)
    body = r.json()
    assert r.status_code == 409 and body["error"] == "app_backup_failed"
    assert body["text"] == {"msg_key": "srv.app_backup_failed", "params": {"error": "disk full"}}
