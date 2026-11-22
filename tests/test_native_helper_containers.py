"""Run natively, ClamAV and Pocket ID start without a container of Kiboto own to copy from: their data
sits in Kiboto data folder, which is a folder of the host, and Kiboto reaches them on loopback."""

import pytest

from backend import runtime
from backend.services import container_mutator, family_signin, hw_helper_container
from backend.services import malware_scan as ms


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    made = {}

    def docker(method, path, body=None, headers=None):
        if path.startswith("/containers/create"):
            made[path.split("name=")[1]] = body
            return 201, {}
        return (404, None) if method == "GET" else (204, None)

    monkeypatch.setattr(container_mutator, "docker_request", docker)
    monkeypatch.setattr(container_mutator, "pull_container_image", lambda image, **k: None)
    return made


def test_the_data_folder_is_the_hosts_own(native):
    assert hw_helper_container.host_data_dir({}) == hw_helper_container.DATA_DIR


def test_clamav_starts_on_loopback(native, tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "_self", lambda: {})
    monkeypatch.setattr(ms, "DATA_DIR", str(tmp_path))
    ms._ensure_container()
    want = native[ms.CONTAINER]
    assert want["HostConfig"]["Binds"] == [f"{hw_helper_container.DATA_DIR}/clamav:/var/lib/clamav"]
    assert want["HostConfig"]["PortBindings"][f"{ms.PORT}/tcp"][0]["HostIp"] == "127.0.0.1"
    assert ms.address({}) == ("127.0.0.1", ms.PORT)


def test_pocket_id_starts_on_its_host_port(native, tmp_path, monkeypatch):
    monkeypatch.setattr(family_signin, "_self", lambda: {})
    monkeypatch.setattr(family_signin, "DATA_DIR", str(tmp_path))
    data = {"enc_key": family_signin.secret_box.seal("e"), "api_key": family_signin.secret_box.seal("a")}
    family_signin._ensure_container(data, "https://nas.example.ts.net:11411")
    want = native[family_signin.CONTAINER]
    assert want["HostConfig"]["Binds"] == [f"{hw_helper_container.DATA_DIR}/pocket-id:/app/data"]
    assert "NetworkMode" not in want["HostConfig"]
    assert family_signin.internal_base({}) == f"http://127.0.0.1:{family_signin.PORT}"
