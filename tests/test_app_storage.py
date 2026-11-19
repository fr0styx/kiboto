"""Re-audit R4: how much space each app uses."""

import os

from backend.services import app_storage


def _df(tmp):
    return {
        "Images": [{"Id": "sha256:aaa", "Size": 300_000_000}, {"Id": "sha256:bbb", "Size": 90_000_000}],
        "Volumes": [
            {"Name": "immich_pg", "UsageData": {"Size": 2_000_000_000}},
            {"Name": "orphan", "UsageData": {"Size": -1}},
        ],
        "Containers": [
            {
                "Id": "1" * 64,
                "Names": ["/immich"],
                "ImageID": "sha256:aaa",
                "State": "running",
                "SizeRw": 5_000_000,
                "Labels": {"com.docker.compose.project": "photos"},
                "Mounts": [
                    {"Type": "volume", "Name": "immich_pg", "Destination": "/var/lib/postgresql"},
                    {"Type": "bind", "Source": str(tmp / "appdata" / "immich"), "Destination": "/config"},
                    {"Type": "bind", "Source": "/mnt/user/media/photos", "Destination": "/photos"},
                    {"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock"},
                ],
            },
            {
                "Id": "2" * 64,
                "Names": ["/pihole"],
                "ImageID": "sha256:bbb",
                "State": "exited",
                "SizeRw": 0,
                "Mounts": [
                    {"Type": "bind", "Source": str(tmp / "appdata" / "immich"), "Destination": "/shared"},
                    {"Type": "bind", "Source": str(tmp / "gone"), "Destination": "/x"},
                    {"Type": "bind", "Source": str(tmp / "sleepy"), "Destination": "/y"},
                ],
            },
            {"Id": "3" * 64, "Names": [], "ImageID": "sha256:zzz", "State": "running"},
        ],
    }


def _tree(tmp):
    d = tmp / "appdata" / "immich" / "db"
    d.mkdir(parents=True)
    (d / "a.bin").write_bytes(b"x" * 1000)
    (tmp / "appdata" / "immich" / "b.bin").write_bytes(b"y" * 500)
    os.symlink(str(d / "a.bin"), str(tmp / "appdata" / "immich" / "link"))  # a link is not counted twice
    (tmp / "sleepy").mkdir()


def test_docker_numbers_alone_walk_nothing(tmp_path):
    _tree(tmp_path)
    out = app_storage.summarize(_df(tmp_path))
    immich = next(a for a in out["apps"] if a["name"] == "immich")
    assert immich["program_bytes"] == 300_000_000 and immich["written_bytes"] == 5_000_000
    assert immich["volumes_bytes"] == 2_000_000_000 and immich["stack"] == "photos" and immich["running"]
    assert immich["shared_folders"] == 1  # the media folder is not the app's data
    assert [f["state"] for f in immich["folders"]] == ["not_measured"]
    assert immich["data_bytes"] == 2_005_000_000
    assert out["folders_measured"] is False and out["apps"][0]["name"] == "immich"  # biggest first
    assert next(a for a in out["apps"] if a["name"] == "3" * 12)["program_bytes"] == 0


def test_folders_are_measured_once_and_sleeping_or_missing_ones_say_so(tmp_path):
    _tree(tmp_path)
    out = app_storage.summarize(_df(tmp_path), walk=True, asleep=lambda p: p.endswith("sleepy"))
    immich = next(a for a in out["apps"] if a["name"] == "immich")
    assert immich["folders"][0] == {"path": str(tmp_path / "appdata" / "immich"), "bytes": 1500, "state": "measured"}
    assert immich["data_bytes"] == 2_005_001_500
    pihole = next(a for a in out["apps"] if a["name"] == "pihole")
    assert [f["state"] for f in pihole["folders"]] == ["counted_elsewhere", "missing", "asleep"]
    assert pihole["data_bytes"] == 0 and out["total_data_bytes"] == 2_005_001_500


def test_the_walk_stops_at_its_time_limit(tmp_path):
    _tree(tmp_path)
    ticks = iter([0.0])
    out = app_storage.summarize(_df(tmp_path), walk=True, asleep=lambda p: False, now=lambda: next(ticks, 0.0))
    assert out["folders_measured"] is True
    size, complete = app_storage.folder_size(str(tmp_path / "appdata"), deadline=-1.0)
    assert (size, complete) == (0, False)
    assert app_storage.folder_size(str(tmp_path / "nowhere"), deadline=1e18) == (0, True)


def test_a_drive_that_cannot_be_identified_counts_as_asleep(monkeypatch):
    from backend.services import rag_standby

    def boom(path):
        raise OSError("no such device")

    monkeypatch.setattr(rag_standby, "resolve_path_backing_dev", boom)
    assert app_storage._asleep("/mnt/x") is True


def test_the_route_and_a_docker_that_does_not_answer(client, monkeypatch):
    from backend.services import docker_client

    assert client.get("/api/docker/apps/space").status_code in (401, 403)
    h = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'password': 'admin'}).json()['token']}"}
    empty = {"Containers": [], "Images": [], "Volumes": []}
    monkeypatch.setattr(docker_client, "request", lambda *a, **k: (200, empty))
    res = client.get("/api/docker/apps/space", headers=h)
    assert res.status_code == 200 and res.json() == {"apps": [], "folders_measured": False, "total_data_bytes": 0}
    assert client.get("/api/docker/apps/space?folders=true", headers=h).json()["folders_measured"] is True
    monkeypatch.setattr(docker_client, "request", lambda *a, **k: (500, {"message": "daemon busy"}))
    res = client.get("/api/docker/apps/space", headers=h)
    assert res.status_code == 503 and "daemon busy" in res.text
    monkeypatch.setattr(docker_client, "request", lambda *a, **k: (502, "bad gateway"))
    assert client.get("/api/docker/apps/space", headers=h).status_code == 503

    def gone(*a, **k):
        raise docker_client.DockerUnavailable(503, "the Docker socket is missing", "/system/df")

    monkeypatch.setattr(docker_client, "request", gone)
    res = client.get("/api/docker/apps/space", headers=h)
    assert res.status_code == 503 and "socket is missing" in res.text
