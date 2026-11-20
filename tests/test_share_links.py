import os
from unittest.mock import patch

import pytest

import backend.api.fs as fs_mod


@pytest.fixture
def share_sandbox(tmp_path, pool_tree):
    links_file = str(tmp_path / "shared_links.json")
    test_file = os.path.join(pool_tree, "media", "readme.txt")

    fs_mod._SHARE_PWD_ATTEMPTS.clear()
    with (
        patch.object(fs_mod, "SHARE_LINKS_FILE", links_file),
        patch.object(fs_mod, "ALLOWED_BROWSE_ROOTS", [str(pool_tree)]),
    ):
        yield {
            "links_file": links_file,
            "test_file": test_file,
            "pool_tree": pool_tree,
        }
    fs_mod._SHARE_PWD_ATTEMPTS.clear()


def test_create_and_access_public_share_link(client, auth_headers, share_sandbox):
    test_file = share_sandbox["test_file"]

    res = client.post(
        "/api/fs/share-links",
        json={
            "path": test_file,
            "expires_hours": 24,
            "label": "My Test File",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert "token" in data
    assert data["filename"] == "readme.txt"
    assert data["label"] == "My Test File"
    assert data["has_password"] is False
    assert data["expires_at"] is not None
    token = data["token"]

    # Public Access without any auth headers
    pub_res = client.get(f"/api/fs/shared/{token}")
    assert pub_res.status_code == 200
    assert pub_res.text == "hello"

    # Info query without counting as download
    info_res = client.get(f"/api/fs/shared/{token}?info=1")
    assert info_res.status_code == 200
    info_data = info_res.json()
    assert info_data["filename"] == "readme.txt"
    assert info_data["download_count"] == 1


def test_share_link_with_password_protection(client, auth_headers, share_sandbox):
    test_file = share_sandbox["test_file"]

    res = client.post(
        "/api/fs/share-links",
        json={
            "path": test_file,
            "password": "SecretPassword123!",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    token = res.json()["token"]

    # Access without password should be rejected
    res_no_pwd = client.get(f"/api/fs/shared/{token}")
    assert res_no_pwd.status_code == 401

    # Access with wrong password should be rejected
    res_wrong_pwd = client.get(f"/api/fs/shared/{token}", headers={"X-Share-Password": "Wrong"})
    assert res_wrong_pwd.status_code == 401

    # Access with correct password in query param
    res_query_pwd = client.post(f"/api/fs/shared/{token}", json={"password": "SecretPassword123!"})
    assert res_query_pwd.status_code == 200
    assert res_query_pwd.text == "hello"

    # Access with correct password in header
    res_hdr_pwd = client.get(f"/api/fs/shared/{token}", headers={"X-Share-Password": "SecretPassword123!"})
    assert res_hdr_pwd.status_code == 200
    assert res_hdr_pwd.text == "hello"


def test_share_link_expiration_and_download_limit(client, auth_headers, share_sandbox):
    test_file = share_sandbox["test_file"]

    # Max 1 download
    res = client.post(
        "/api/fs/share-links",
        json={
            "path": test_file,
            "max_downloads": 1,
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    token = res.json()["token"]

    # 1st download succeeds
    res1 = client.get(f"/api/fs/shared/{token}")
    assert res1.status_code == 200

    # 2nd download is blocked with 410 Gone
    res2 = client.get(f"/api/fs/shared/{token}")
    assert res2.status_code == 410
    assert "limit reached" in res2.text.lower()


@pytest.mark.parametrize("folder", [False, True])
def test_downloads_started_side_by_side_keep_to_the_limit(client, auth_headers, share_sandbox, monkeypatch, folder):
    from backend.api.files import share_links

    path = os.path.dirname(share_sandbox["test_file"]) if folder else share_sandbox["test_file"]
    res = client.post("/api/fs/share-links", json={"path": path, "max_downloads": 1}, headers=auth_headers)
    token = res.json()["token"]
    real_ip = share_links._get_client_ip
    calls = []

    def another_download_was_counted_meanwhile(request):
        calls.append(1)
        if len(calls) == 2:  # past the check at the top, before this one is counted
            links = share_links._load_share_links()
            links[token]["download_count"] = 1
            share_links._save_share_links(links)
        return real_ip(request)

    monkeypatch.setattr(share_links, "_get_client_ip", another_download_was_counted_meanwhile)
    r = client.get(f"/api/fs/shared/{token}")
    assert r.status_code == 410 and len(calls) >= 2
    assert share_links._load_share_links()[token]["download_count"] == 1
    assert share_links._SHARE_ZIP_ACTIVE == {}  # a refused folder download gave its slot back


def test_share_link_revoke_and_list(client, auth_headers, share_sandbox):
    test_file = share_sandbox["test_file"]

    res = client.post(
        "/api/fs/share-links",
        json={"path": test_file},
        headers=auth_headers,
    )
    assert res.status_code == 200
    token = res.json()["token"]

    # List links
    list_res = client.get("/api/fs/share-links", headers=auth_headers)
    assert list_res.status_code == 200
    items = list_res.json()
    assert any(i["token"] == token for i in items)

    # Revoke
    del_res = client.delete(f"/api/fs/share-links/{token}", headers=auth_headers)
    assert del_res.status_code == 200

    # Access after revocation returns 404
    get_res = client.get(f"/api/fs/shared/{token}")
    assert get_res.status_code == 404
