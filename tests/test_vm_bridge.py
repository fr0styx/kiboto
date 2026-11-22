"""The bridge virtual machines join, on a machine set up for Kiboto: a trial like an address change."""

import os

import pytest

from backend import runtime
from backend.hardware.net import managed


class Box:
    def __init__(self):
        self.seen, self.waiting, self.networkd, self.timer = [], [], True, False

    def __call__(self, cmd, timeout=20):
        self.seen.append(cmd)
        if cmd[:2] == ["systemctl", "is-active"]:
            if "systemd-networkd" in cmd:
                return (0, "active\nactive") if self.networkd else (3, "inactive\nactive")
            return (0, "active") if self.timer else (3, "inactive")
        if cmd[0] == "systemd-run":
            self.timer = True
        if cmd[:2] == ["systemctl", "stop"]:
            self.timer = False
        return 0, ""

    def later(self, seconds, what):
        self.waiting.append(what)

    def a_moment_passes(self):
        waiting, self.waiting = self.waiting, []
        for what in waiting:
            what()


@pytest.fixture
def box(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    for name in ("enp1s0", "br0"):
        (tmp_path / "sys" / name).mkdir(parents=True)
    (tmp_path / "sys" / "enp1s0" / "address").write_text("52:54:00:12:34:56\n")
    (tmp_path / "network").mkdir()
    monkeypatch.setattr(managed, "DIR", str(tmp_path / "network"))
    monkeypatch.setattr(managed, "SYS_NET", str(tmp_path / "sys"))
    monkeypatch.setattr(managed, "LEASES", str(tmp_path / "leases"))
    monkeypatch.setattr(managed, "STATE", str(tmp_path / "data" / "network_trial.json"))
    monkeypatch.setattr(managed, "QEMU_BRIDGES", str(tmp_path / "qemu" / "bridge.conf"))
    made = Box()
    monkeypatch.setattr(managed, "run", made)
    monkeypatch.setattr(managed, "after", made.later)
    made.root = tmp_path
    return made


def net(box, name):
    path = box.root / "network" / name
    return path.read_text() if path.exists() else None


STATIC = "[Match]\nName=enp1s0\n\n[Network]\nAddress=192.168.1.50/24\nGateway=192.168.1.1\nDNS=1.1.1.1\n"


def test_the_bridge_takes_the_port_and_its_address_with_the_ports_hardware_address(box):
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(STATIC)
    answer = managed.start_bridge_trial(True, "enp1s0")
    assert answer["status"] == "trial" and answer["url"] == ""  # the address stays: the page keeps it
    assert net(box, "05-kiboto-br0.netdev") is None  # nothing changes before the way back is armed
    box.a_moment_passes()
    netdev = net(box, "05-kiboto-br0.netdev")
    assert "Name=br0\nKind=bridge\nMACAddress=52:54:00:12:34:56" in netdev and "STP=no" in netdev
    assert net(box, "05-kiboto-br0.network") == STATIC.replace("Name=enp1s0", "Name=br0")
    assert net(box, "05-kiboto-enp1s0.network").endswith("[Match]\nName=enp1s0\n\n[Network]\nBridge=br0\n")
    assert (box.root / "qemu" / "bridge.conf").read_text() == "allow br0\n"  # QEMU may join it
    assert managed.bridge_status() == {"on": True, "port": "enp1s0", "name": "br0"}
    assert ["networkctl", "reconfigure", "enp1s0"] in box.seen and ["networkctl", "reconfigure", "br0"] in box.seen


def test_a_port_without_kibotos_file_moves_its_address_from_the_router(box):
    managed.start_bridge_trial(True, "enp1s0")
    box.a_moment_passes()
    assert "DHCP=yes" in net(box, "05-kiboto-br0.network") and "Name=br0" in net(box, "05-kiboto-br0.network")


def test_a_fixed_address_the_machine_shows_moves_to_the_bridge(box, monkeypatch):
    monkeypatch.setattr(managed, "mode_of", lambda iface: "static")
    now = {"ip_address": "192.168.1.60", "cidr": 24, "gateway": "192.168.1.1", "dns1": "1.1.1.1", "dns2": ""}
    managed.start_bridge_trial(True, "enp1s0", now)
    box.a_moment_passes()
    text = net(box, "05-kiboto-br0.network")
    assert "Address=192.168.1.60/24" in text and "Gateway=192.168.1.1" in text and "DNS=1.1.1.1" in text
    managed.go_back(None)
    with pytest.raises(ValueError, match="could not be read"):
        managed.start_bridge_trial(True, "enp1s0", {})


def test_a_bridge_nobody_kept_goes_and_the_port_gets_its_settings_back(box):
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(STATIC)
    managed.start_bridge_trial(True, "enp1s0")
    box.a_moment_passes()
    assert managed.main(["managed", "revert"]) == 0
    assert net(box, "05-kiboto-enp1s0.network") == STATIC
    assert net(box, "05-kiboto-br0.netdev") is None and net(box, "05-kiboto-br0.network") is None
    assert ["ip", "link", "delete", "br0"] in box.seen  # networkd never takes a bridge away by itself


def test_taking_the_bridge_away_gives_the_port_its_address_again(box):
    managed.start_bridge_trial(True, "enp1s0")
    box.a_moment_passes()
    managed.keep(None)
    box.seen.clear()
    managed.start_bridge_trial(False)
    box.a_moment_passes()
    managed.keep(None)
    assert "DHCP=yes" in net(box, "05-kiboto-enp1s0.network") and "Name=enp1s0" in net(box, "05-kiboto-enp1s0.network")
    assert net(box, "05-kiboto-br0.netdev") is None and ["ip", "link", "delete", "br0"] in box.seen
    assert managed.bridge_status() == {"on": False, "port": "", "name": "br0"}


def test_what_cannot_be_is_refused(box):
    with pytest.raises(ValueError, match="no bridge to take away"):
        managed.start_bridge_trial(False)
    with pytest.raises(ValueError, match="not a network port"):
        managed.start_bridge_trial(True, "docker0")
    managed.start_bridge_trial(True, "enp1s0")
    box.a_moment_passes()
    managed.keep(None)
    with pytest.raises(ValueError, match="already there"):
        managed.start_bridge_trial(True, "enp1s0")
    box.networkd = False
    with pytest.raises(RuntimeError, match="systemd-networkd"):
        managed.start_bridge_trial(False)


def test_qemus_list_keeps_what_it_had(box):
    os.makedirs(box.root / "qemu")
    (box.root / "qemu" / "bridge.conf").write_text("allow virbr0")
    managed._let_qemu_use("br0")
    managed._let_qemu_use("br0")
    assert (box.root / "qemu" / "bridge.conf").read_text() == "allow virbr0\nallow br0\n"


def test_an_older_trial_with_one_file_is_still_put_back(box):
    import json

    path = box.root / "network" / "05-kiboto-enp1s0.network"
    path.write_text("new")
    os.makedirs(box.root / "data")
    (box.root / "data" / "network_trial.json").write_text(
        json.dumps(
            {"id": "k" * 32, "iface": "enp1s0", "path": str(path), "before": STATIC, "started": 0, "timeout": 60}
        )
    )
    managed.go_back(None)
    assert path.read_text() == STATIC


def test_the_page_sees_the_bridge_and_turns_it_on(box, client, auth_headers, monkeypatch):
    from backend.hardware.net import host_ip
    from backend.services import host_basics

    monkeypatch.setattr(host_ip, "get_host_ip_config", lambda: {"interface": "enp1s0", "ip_address": "10.0.0.5"})
    monkeypatch.setattr(host_basics, "run", lambda cmd, timeout=20: (0, ""))
    st = client.get("/api/system/machine", headers=auth_headers).json()
    assert st["bridge"] == {"on": False, "port": "", "name": "br0", "can": True}
    r = client.post("/api/network/host/bridge", headers=auth_headers, json={"on": True})
    assert r.status_code == 200 and r.json()["status"] == "trial"
    r = client.post("/api/network/host/bridge", headers=auth_headers, json={"on": True})
    assert r.status_code == 400  # one trial at a time
    box.networkd = False
    managed.go_back(None)
    r = client.post("/api/network/host/bridge", headers=auth_headers, json={"on": False})
    assert r.status_code == 502


def test_a_guest_does_not_bridge_its_host(client, auth_headers):
    r = client.post("/api/network/host/bridge", headers=auth_headers, json={"on": True})
    assert r.status_code == 409 and r.json()["error"] == "not_on_this_host"
