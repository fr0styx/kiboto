"""Files never deletes, renames or moves the system's own folders, a drive, or Kiboto's data."""

import pytest
from fastapi import HTTPException

from backend.services import path_access


@pytest.mark.parametrize("path", ["/mnt/user/appdata", "/mnt/user/system", "/mnt/cache/domains", "/mnt/disk1/isos"])
def test_the_system_folders_at_a_pool_top(path):
    with pytest.raises(HTTPException) as e:
        path_access.refuse_system_folder(path)
    assert e.value.status_code == 403


@pytest.mark.parametrize(
    "path", ["/mnt/user/Media", "/mnt/user/appdata/plex/cache", "/mnt/user/Media/system", "", None]
)
def test_other_folders_and_what_is_inside_pass(path):
    path_access.refuse_system_folder(path)


def test_a_drive_and_a_folder_holding_kibotos_data(tmp_path, monkeypatch):
    import backend.fsutil as fsutil

    ours = tmp_path / "pool" / "apps" / "kiboto"
    ours.mkdir(parents=True)
    (tmp_path / "pool" / "Films").mkdir()
    monkeypatch.setattr(fsutil, "protected_dirs", lambda: [str(ours)])
    for path in (tmp_path / "pool", tmp_path / "pool" / "apps", ours):
        with pytest.raises(HTTPException):
            path_access.refuse_system_folder(str(path))
    path_access.refuse_system_folder(str(tmp_path / "pool" / "Films"))
    monkeypatch.setattr(path_access.os.path, "ismount", lambda p: p == str(tmp_path / "pool" / "Films"))
    with pytest.raises(HTTPException):
        path_access.refuse_system_folder(str(tmp_path / "pool" / "Films"))


def test_the_routes_refuse_before_touching_anything(client, auth_headers):
    r = client.post("/api/fs/rename", json={"path": "/mnt/user/appdata", "new_name": "old"}, headers=auth_headers)
    assert r.status_code == 403
    r = client.post("/api/fs/delete", json={"path": "/mnt/user/system"}, headers=auth_headers)
    assert r.status_code == 403
    for route in ("/api/fs/transfer", "/api/fs/transfer/async"):
        body = {"sources": ["/mnt/user/appdata"], "destination_dir": "/mnt/user", "action": "move"}
        assert client.post(route, json=body, headers=auth_headers).status_code == 403
