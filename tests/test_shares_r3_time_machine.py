"""Shares R3: Mac backup folders with their size limits; changing one keeps the rest of the share."""

from types import SimpleNamespace

import pytest

from backend.api import storage


class _Share(SimpleNamespace):
    def model_copy(self, update):
        return _Share(**{**self.__dict__, **update})


class _Engine:
    def __init__(self):
        self.shares = {
            "macs": _Share(name="macs", timemachine=True, timemachine_quota_gb=500, read_only=False, comment="keep"),
            "photos": _Share(name="photos", timemachine=False, timemachine_quota_gb=None),
        }
        self.saved = []

    def list_shares(self):
        return list(self.shares.values())

    def get_share(self, name):
        return self.shares.get(name)

    def add_or_update_share(self, share):
        if share.name == "bad":
            raise ValueError("no")
        self.saved.append(share)
        self.shares[share.name] = share


@pytest.fixture
def managed(monkeypatch):
    eng = _Engine()
    caps = SimpleNamespace(is_observer_mode=False)
    monkeypatch.setattr(storage, "get_storage_platform", lambda: SimpleNamespace(get_capabilities=lambda: caps))
    monkeypatch.setattr("backend.services.samba_engine.get_samba_engine", lambda: eng)
    monkeypatch.setattr("backend.services.nas_name.refresh", lambda: None)
    eng.caps = caps
    return eng


def test_the_folders_macs_back_up_to(client, auth_headers, managed):
    body = client.get("/api/storage/time-machine", headers=auth_headers).json()
    assert body == {"managed": True, "folders": [{"name": "macs", "size_gb": 500}]}
    managed.caps.is_observer_mode = True
    assert client.get("/api/storage/time-machine", headers=auth_headers).json() == {"managed": False, "folders": []}


def test_changing_the_size_keeps_everything_else(client, auth_headers, managed):
    r = client.put("/api/storage/shares/macs/time-machine", json={"size_gb": 800}, headers=auth_headers)
    assert r.json() == {"name": "macs", "size_gb": 800, "timemachine": True}
    s = managed.saved[-1]
    assert s.timemachine_quota_gb == 800 and s.comment == "keep" and s.read_only is False


def test_stopping_and_the_refusals(client, auth_headers, managed):
    r = client.put("/api/storage/shares/macs/time-machine", json={"size_gb": 0}, headers=auth_headers)
    assert r.json()["timemachine"] is False and managed.saved[-1].timemachine is False
    assert (
        client.put("/api/storage/shares/nope/time-machine", json={"size_gb": 5}, headers=auth_headers).status_code
        == 404
    )
    managed.shares["bad"] = _Share(name="bad", timemachine=False)
    assert (
        client.put("/api/storage/shares/bad/time-machine", json={"size_gb": 5}, headers=auth_headers).status_code == 400
    )
    assert (
        client.put("/api/storage/shares/macs/time-machine", json={"size_gb": -1}, headers=auth_headers).status_code
        == 422
    )
    managed.caps.is_observer_mode = True
    assert (
        client.put("/api/storage/shares/macs/time-machine", json={"size_gb": 5}, headers=auth_headers).status_code
        == 403
    )
