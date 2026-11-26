"""VLANs and packet sizes on a machine set up for Kiboto: trials like an address change."""

import pytest

from backend import runtime
from backend.hardware.net import host, managed


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
    port = tmp_path / "sys" / "enp1s0"
    port.mkdir(parents=True)
    (port / "address").write_text("52:54:00:12:34:56\n")
    (port / "mtu").write_text("1500\n")
    (port / "ifindex").write_text("2\n")
    (tmp_path / "leases").mkdir()
    (tmp_path / "leases" / "2").write_text("lease")  # an address from the router, by the fallback file
    (tmp_path / "network").mkdir()
    monkeypatch.setattr(managed, "DIR", str(tmp_path / "network"))
    monkeypatch.setattr(managed, "SYS_NET", str(tmp_path / "sys"))
    monkeypatch.setattr(managed, "LEASES", str(tmp_path / "leases"))
    monkeypatch.setattr(managed, "STATE", str(tmp_path / "data" / "network_trial.json"))
    made = Box()
    monkeypatch.setattr(managed, "run", made)
    monkeypatch.setattr(managed, "after", made.later)
    made.root = tmp_path
    return made


def net(box, name):
    path = box.root / "network" / name
    return path.read_text() if path.exists() else None


STATIC = "[Match]\nName=enp1s0\n\n[Network]\nAddress=192.168.1.50/24\nGateway=192.168.1.1\n"


def test_a_vlan_is_a_trial_and_the_port_keeps_its_address(box):
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(STATIC)
    answer = managed.start_vlan_trial("enp1s0", 20)
    assert answer["status"] == "trial" and answer["canary_id"]
    assert net(box, "05-kiboto-enp1s0.20.netdev") is None  # nothing before the way back is armed
    assert any(c[0] == "systemd-run" for c in box.seen)
    box.a_moment_passes()
    assert "Name=enp1s0.20\nKind=vlan\n\n[VLAN]\nId=20" in net(box, "05-kiboto-enp1s0.20.netdev")
    assert "Name=enp1s0.20" in net(box, "05-kiboto-enp1s0.20.network")
    assert "Address=" not in net(box, "05-kiboto-enp1s0.20.network")  # no address of its own yet
    assert net(box, "05-kiboto-enp1s0.network") == STATIC + "VLAN=enp1s0.20\n"
    assert ["networkctl", "reconfigure", "enp1s0"] in box.seen
    managed.keep(None)
    # a second VLAN joins the first; going back takes only the second away
    managed.start_vlan_trial("enp1s0", 30)
    box.a_moment_passes()
    assert net(box, "05-kiboto-enp1s0.network").endswith("VLAN=enp1s0.20\nVLAN=enp1s0.30\n")
    managed.go_back(None)
    assert net(box, "05-kiboto-enp1s0.network") == STATIC + "VLAN=enp1s0.20\n"
    assert net(box, "05-kiboto-enp1s0.30.netdev") is None


def test_a_port_on_the_router_address_gets_a_file_of_its_own_for_its_vlan(box):
    managed.start_vlan_trial("enp1s0", 7)
    box.a_moment_passes()
    own = net(box, "05-kiboto-enp1s0.network")
    assert "Name=enp1s0" in own and "DHCP=yes" in own and "VLAN=enp1s0.7" in own


def test_what_a_vlan_cannot_be(box):
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(STATIC)
    for parent, number, said in [
        ("enp1s0", 0, "between 1 and 4094"),
        ("enp1s0", 4095, "between 1 and 4094"),
        ("enp1s0", True, "between 1 and 4094"),
        ("eth9", 5, "not a network port"),
        ("enp1s0.20", 5, "not a network port"),
        ("enp1s0", 123456, "between 1 and 4094"),
    ]:
        with pytest.raises(ValueError, match=said):
            managed.start_vlan_trial(parent, number)
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(STATIC + "Bridge=br0\n")
    with pytest.raises(ValueError, match="bridge or bond"):
        managed.start_vlan_trial("enp1s0", 5)
    box.networkd = False
    with pytest.raises(RuntimeError, match="systemd-networkd"):
        managed.start_vlan_trial("enp1s0", 5)
    assert not any(c[0] == "systemd-run" for c in box.seen)  # nothing was armed


def test_only_a_vlan_kiboto_made_is_taken_away(box):
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(STATIC + "VLAN=enp1s0.20\n")
    (box.root / "network" / "05-kiboto-enp1s0.20.netdev").write_text("[NetDev]\nName=enp1s0.20\nKind=vlan\n")
    (box.root / "network" / "05-kiboto-enp1s0.20.network").write_text("[Match]\nName=enp1s0.20\n")
    with pytest.raises(ValueError, match="not a VLAN Kiboto made"):
        managed.start_vlan_removal("enp1s0.99")
    with pytest.raises(ValueError, match="not a VLAN Kiboto made"):
        managed.start_vlan_removal("../../etc")
    managed.start_vlan_removal("enp1s0.20")
    box.a_moment_passes()
    assert net(box, "05-kiboto-enp1s0.20.netdev") is None and net(box, "05-kiboto-enp1s0.20.network") is None
    assert net(box, "05-kiboto-enp1s0.network") == STATIC
    assert ["ip", "link", "delete", "enp1s0.20"] in box.seen  # networkd never takes a device away


def test_a_packet_size_is_a_trial_and_the_size_it_has_is_nothing_to_try(box):
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(STATIC)
    assert managed.start_mtu_trial("enp1s0", 1500)["changed"] is False
    assert not any(c[0] == "systemd-run" for c in box.seen)
    for size in (575, 9217, True):
        with pytest.raises(ValueError, match="between 576 and 9216"):
            managed.start_mtu_trial("enp1s0", size)
    assert managed.start_mtu_trial("enp1s0", 9000)["status"] == "trial"
    box.a_moment_passes()
    assert net(box, "05-kiboto-enp1s0.network") == STATIC + "\n[Link]\nMTUBytes=9000\n"
    managed.go_back(None)
    assert net(box, "05-kiboto-enp1s0.network") == STATIC


def test_the_page_may_change_vlans_and_packet_sizes_here_and_nothing_else_new(box, monkeypatch):
    caps = host.ManagedHostNetwork().capabilities()["can_change"]
    assert caps == {
        "address": True,
        "mtu": True,
        "speed": False,
        "wake_on_lan": False,
        "bond": False,
        "bridge": False,
        "vlan": True,
    }
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(STATIC)
    h = host.ManagedHostNetwork()
    assert h.apply("vlan", "enp1s0", {"vlan_id": 20, "alias": "cameras"})["status"] == "trial"
    managed.go_back(None)
    assert h.apply("port", "enp1s0", {"mtu": 1500}) == {
        "status": "ok",
        "interface": "enp1s0",
        "mtu": 1500,
        "changed": False,
    }
    with pytest.raises(host.NotOnThisHost):
        h.apply("port", "enp1s0", {"mtu": 9000, "wol_enabled": True})
    with pytest.raises(host.NotOnThisHost):
        h.apply("bond", "bond0", {"mode": "1", "slaves": ["enp1s0"]})
    with pytest.raises(ValueError, match="between 1 and 4094"):
        h.apply("vlan", "enp1s0", {"vlan_id": "20"})
