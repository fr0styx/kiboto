"""On a machine Kiboto runs, its Time Machine shares are announced to Macs (the machine's own smbd
serves them; there is no Samba container to look for)."""

from types import SimpleNamespace

from backend.services import nas_name, samba_engine, samba_host


class Engine:
    def __init__(self, sidecar="exited"):
        self.sidecar = sidecar

    def check_sidecar(self):
        return {"state": self.sidecar}

    def list_shares(self):
        return [SimpleNamespace(name="timemachine", timemachine=True), SimpleNamespace(name="files", timemachine=False)]


def test_a_managed_machine_announces_its_time_machine_shares(monkeypatch):
    monkeypatch.setattr(samba_engine, "get_samba_engine", lambda: Engine())
    monkeypatch.setattr(samba_host, "active", lambda: True)
    monkeypatch.setattr(samba_host, "running", lambda do=None: True)
    assert nas_name.timemachine_shares() == ["timemachine"]
    monkeypatch.setattr(samba_host, "running", lambda do=None: False)
    assert nas_name.timemachine_shares() == []  # smbd is down: nothing to back up to


def test_elsewhere_the_container_decides(monkeypatch):
    monkeypatch.setattr(samba_host, "active", lambda: False)
    monkeypatch.setattr(samba_engine, "get_samba_engine", lambda: Engine("running"))
    assert nas_name.timemachine_shares() == ["timemachine"]
    monkeypatch.setattr(samba_engine, "get_samba_engine", lambda: Engine("exited"))
    assert nas_name.timemachine_shares() == []
