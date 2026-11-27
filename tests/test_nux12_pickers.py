"""NUX-12: a child's devices are picked from what AdGuard has seen, and the install dialog starts
from where this host keeps app data."""

import pytest

from backend.services import adguard_kids, app_catalog


def test_recent_devices_with_their_names(monkeypatch):
    clients = {
        "auto_clients": [
            {"ip": "192.0.2.20", "name": "lenas-tablet", "source": "rdns"},
            {"ip": "192.0.2.21", "name": "192.0.2.21"},
            {"ip": "192.0.2.22", "name": ""},
            {"name": "no address"},
            "junk",
        ],
        "clients": [{"name": "zettnas-kid-lena", "ids": ["192.0.2.20"]}],
    }
    monkeypatch.setattr(adguard_kids, "_settings", lambda: {"url": "http://ag", "user": "u", "password": "p"})
    monkeypatch.setattr(
        adguard_kids,
        "_call",
        lambda s, m, path, body=None, opener=None: clients if path == "/control/clients" else None,
    )
    assert adguard_kids.recent_devices() == [
        {"id": "192.0.2.20", "name": "lenas-tablet"},
        {"id": "192.0.2.21", "name": "192.0.2.21"},
        {"id": "192.0.2.22", "name": "192.0.2.22"},
    ]


def test_the_devices_api_says_why_there_are_none(client, auth_headers, monkeypatch):
    def refuse(*a, **k):
        raise adguard_kids.AdGuardError("Connect AdGuard Home first.")

    monkeypatch.setattr(adguard_kids, "recent_devices", refuse)
    r = client.get("/api/family-filter/devices", headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"devices": [], "error": "Connect AdGuard Home first."}


@pytest.fixture(autouse=True)
def _fresh_root():
    app_catalog._STORAGE_ROOT.clear()
    yield
    app_catalog._STORAGE_ROOT.clear()


def test_the_storage_root_follows_zettnas_own_data_folder(monkeypatch):
    me = {
        "Mounts": [
            {"Destination": "/other", "Source": "/x/y"},
            {"Destination": app_catalog.DATA_DIR, "Source": "/mnt/tank/apps/zettnas/"},
        ]
    }
    monkeypatch.setattr(app_catalog, "_docker_request", lambda *a, **k: (200, me))
    assert app_catalog.default_storage_root() == "/mnt/tank/apps"
    monkeypatch.setattr(app_catalog, "_docker_request", lambda *a, **k: 1 / 0)
    assert app_catalog.default_storage_root() == "/mnt/tank/apps"  # kept


def test_the_storage_root_falls_back_to_unraids(monkeypatch):
    def down(*a, **k):
        raise OSError("no socket")

    monkeypatch.setattr(app_catalog, "_docker_request", down)
    assert app_catalog.default_storage_root() == "/mnt/user/appdata"
    app_catalog._STORAGE_ROOT.clear()
    monkeypatch.setattr(
        app_catalog,
        "_docker_request",
        lambda *a, **k: (200, {"Mounts": [{"Destination": app_catalog.DATA_DIR, "Source": "/data"}]}),
    )
    assert app_catalog.default_storage_root() == "/mnt/user/appdata"  # not "/"


def test_the_defaults_api(client, auth_headers, monkeypatch):
    monkeypatch.setattr(app_catalog, "default_storage_root", lambda: "/srv/apps")
    assert client.get("/api/docker/catalog/defaults", headers=auth_headers).json() == {"storage_root": "/srv/apps"}


def test_in_a_container_the_apps_folder_is_one_the_host_and_kiboto_share(monkeypatch, tmp_path):
    """#71: the folder that holds Kiboto's data folder on the host (/opt/kiboto) was suggested,
    though only the host had it: Kiboto made the app's folders inside its own container."""
    from backend import config

    monkeypatch.setattr(config, "POOL_PATH", "/mnt/storage")
    data_on_host = {"Destination": app_catalog.DATA_DIR, "Source": "/host-only/kiboto/data"}
    shared = {"Destination": "/mnt/storage", "Source": "/mnt/storage"}
    other = {"Destination": "/mnt/media", "Source": "/mnt/media"}
    assert app_catalog._root_from_mounts([data_on_host, other, shared], "x") == "/mnt/storage/appdata"
    assert app_catalog._root_from_mounts([data_on_host, other], "x") == "/mnt/media/appdata"
    here = tmp_path / "apps"
    (here / "kiboto").mkdir(parents=True)
    mine = {"Destination": app_catalog.DATA_DIR, "Source": str(here / "kiboto")}
    assert app_catalog._root_from_mounts([mine, other], "x") == str(here)  # there in here too: as before
    assert app_catalog._root_from_mounts([{"Destination": "/srv", "Source": "/srv"}], "x") == "x"
