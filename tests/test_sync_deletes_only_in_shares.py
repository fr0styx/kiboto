"""A cloud sync deletes only inside shared folders, and never touches Kiboto's own data."""

import pytest

from backend.services import app_catalog
from backend.services import rclone_engine as re_mod


@pytest.fixture
def jobs(monkeypatch):
    started = []
    engine = re_mod.get_rclone_engine()
    monkeypatch.setattr(engine, "checked_location", lambda spec, confine_local=True: spec)
    monkeypatch.setattr(engine, "start_sync_job", lambda **kw: started.append(kw) or {"id": "j1"})
    monkeypatch.setattr(app_catalog, "share_mounts", lambda: {"Media": "/mnt/user/Media"})
    return started


@pytest.mark.parametrize(
    "src,dst,action",
    [
        ("cloud:photos", "/mnt/user", "sync"),
        ("cloud:photos", "/mnt/cache", "sync"),
        ("cloud:photos", "/mnt/user/appdata", "sync"),
        ("/mnt/user/appdata", "cloud:old", "move"),
        ("/mnt/user", "/mnt/user/Media/copy", "move"),
    ],
)
def test_a_job_that_deletes_outside_the_shared_folders_is_refused(client, auth_headers, jobs, src, dst, action):
    r = client.post("/api/remotes/sync", json={"src": src, "dst": dst, "action": action}, headers=auth_headers)
    assert r.status_code == 403, r.text
    assert jobs == []


@pytest.mark.parametrize(
    "src,dst,action",
    [
        ("cloud:photos", "/mnt/user/Media/Photos", "sync"),
        ("/mnt/user/Media/old", "cloud:archive", "move"),
        ("cloud:photos", "/mnt/user", "copy"),  # a copy deletes nothing
        ("/mnt/user/appdata", "cloud:backup", "sync"),  # the source of a sync is only read
    ],
)
def test_other_jobs_start_with_kibotos_data_left_out(client, auth_headers, jobs, monkeypatch, src, dst, action):
    import backend.fsutil as fsutil

    monkeypatch.setattr(fsutil, "protected_rclone_excludes", lambda base: ["--exclude", f"{base}/kb/**"])
    r = client.post("/api/remotes/sync", json={"src": src, "dst": dst, "action": action}, headers=auth_headers)
    assert r.status_code == 200, r.text
    local = src if src.startswith("/") else dst
    assert jobs[-1]["extra_flags"] == ["--exclude", f"{local}/kb/**"]
