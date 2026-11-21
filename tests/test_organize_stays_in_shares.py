"""The film tidy-up moves films only out of, and puts them only into, shared folders."""

import pytest

from backend.services import app_catalog


@pytest.fixture
def done(monkeypatch):
    from backend.api import media

    applied = []
    monkeypatch.setattr(media, "_validate_media_path", lambda path, principal, must_exist=True: path)
    monkeypatch.setattr(
        media, "apply_organize", lambda items, action, hardlink: applied.append(items) or {"moved": len(items)}
    )
    monkeypatch.setattr(
        app_catalog, "share_mounts", lambda: {"Films": "/mnt/user/Films", "Downloads": "/mnt/user/Downloads"}
    )
    return applied


def _apply(client, headers, src, dst, action="move", hardlink=False):
    body = {"items": [{"source_path": src, "destination_path": dst}], "action": action, "hardlink": hardlink}
    return client.post("/api/media/organize/apply", json=body, headers=headers)


def test_films_move_between_shared_folders(client, auth_headers, done):
    r = _apply(client, auth_headers, "/mnt/user/Downloads/a.mkv", "/mnt/user/Films/A (2020)/A (2020).mkv")
    assert r.status_code == 200 and len(done) == 1


@pytest.mark.parametrize(
    "src,dst,action,hardlink",
    [
        ("/mnt/user/appdata/frigate/clip.mp4", "/mnt/user/Films/clip.mp4", "move", False),
        ("/mnt/user/Downloads/a.mkv", "/mnt/user/appdata/a.mkv", "copy", False),
        ("/mnt/user/Downloads/a.mkv", "/mnt/cache/a.mkv", "move", True),
    ],
)
def test_outside_the_shared_folders_nothing_happens(client, auth_headers, done, src, dst, action, hardlink):
    assert _apply(client, auth_headers, src, dst, action, hardlink).status_code == 403
    assert done == []


def test_a_copy_or_link_may_read_from_anywhere(client, auth_headers, done):
    assert _apply(client, auth_headers, "/mnt/user/appdata/x/a.mkv", "/mnt/user/Films/a.mkv", "copy").status_code == 200
    assert (
        _apply(client, auth_headers, "/mnt/user/appdata/x/a.mkv", "/mnt/user/Films/b.mkv", "move", True).status_code
        == 200
    )
