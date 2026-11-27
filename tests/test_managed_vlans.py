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


def test_the_page_may_change_vlans_packet_sizes_and_the_bond_here(box, monkeypatch):
    caps = host.ManagedHostNetwork().capabilities()["can_change"]
    assert caps == {
        "address": True,
        "mtu": True,
        "speed": False,
        "wake_on_lan": True,
        "bond": True,
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
        h.apply("port", "enp1s0", {"mtu": 9000, "speed": 1000})
    with pytest.raises(host.NotOnThisHost):
        h.apply("bridge", "br0", {"members": ["enp1s0"]})
    with pytest.raises(ValueError, match="between 1 and 4094"):
        h.apply("vlan", "enp1s0", {"vlan_id": "20"})


def second_port(box):
    port = box.root / "sys" / "enp2s0"
    port.mkdir(parents=True, exist_ok=True)
    (port / "address").write_text("52:54:00:12:34:57\n")
    (port / "mtu").write_text("1500\n")


def test_a_bond_takes_the_first_ports_address_and_hardware_address(box):
    second_port(box)
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(STATIC)
    answer = managed.start_bond_trial(["enp1s0", "enp2s0"], "1", 100)
    assert answer["status"] == "trial"
    box.a_moment_passes()
    netdev = net(box, "05-kiboto-bond0.netdev")
    assert "Kind=bond\nMACAddress=52:54:00:12:34:56" in netdev and "Mode=active-backup" in netdev
    assert "MIIMonitorSec=100ms" in netdev and "# first: enp1s0" in netdev
    assert net(box, "05-kiboto-bond0.network") == STATIC.replace("Name=enp1s0", "Name=bond0")
    assert net(box, "05-kiboto-enp1s0.network").endswith("Name=enp1s0\n\n[Network]\nBond=bond0\nPrimarySlave=true\n")
    assert net(box, "05-kiboto-enp2s0.network").endswith("Name=enp2s0\n\n[Network]\nBond=bond0\n")
    assert managed.bond_status() == {"on": True, "members": ["enp1s0", "enp2s0"], "first": "enp1s0", "name": "bond0"}
    managed.keep(None)
    # taken apart: the address back on the first port, the other back on the router's address
    managed.start_bond_removal()
    box.a_moment_passes()
    assert net(box, "05-kiboto-enp1s0.network") == STATIC
    assert net(box, "05-kiboto-enp2s0.network") is None and net(box, "05-kiboto-bond0.netdev") is None
    assert ["ip", "link", "delete", "bond0"] in box.seen


def test_802_3ad_asks_the_switch_quickly_and_going_back_undoes_a_bond(box):
    second_port(box)
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(STATIC)
    managed.start_bond_trial(["enp1s0", "enp2s0"], "4", 200)
    box.a_moment_passes()
    assert "Mode=802.3ad\nMIIMonitorSec=200ms\nLACPTransmitRate=fast" in net(box, "05-kiboto-bond0.netdev")
    managed.go_back(None)
    assert net(box, "05-kiboto-enp1s0.network") == STATIC and net(box, "05-kiboto-bond0.netdev") is None


def test_what_a_bond_cannot_be(box):
    second_port(box)
    for members, mode, miimon, said in [
        (["enp1s0"], "1", 100, "two or more"),
        (["enp1s0", "enp1s0"], "1", 100, "two or more"),
        (["enp1s0", "eth9"], "1", 100, "cannot join a bond|can join a bond"),
        (["enp1s0", "enp2s0"], "3", 100, "bonding modes"),
        (["enp1s0", "enp2s0"], "1", 5, "10 to 1000"),
        ("enp1s0", "1", 100, "two or more"),
    ]:
        with pytest.raises(ValueError, match=said):
            managed.start_bond_trial(members, mode, miimon)
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(STATIC + "VLAN=enp1s0.20\n")
    with pytest.raises(ValueError, match="bridge or VLANs"):
        managed.start_bond_trial(["enp1s0", "enp2s0"])
    with pytest.raises(ValueError, match="no bond"):
        managed.start_bond_removal()
    assert not any(c[0] == "systemd-run" for c in box.seen)


def test_the_page_makes_one_bond_here(box):
    second_port(box)
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(STATIC)
    h = host.ManagedHostNetwork()
    assert h.capabilities()["can_change"]["bond"] is True
    with pytest.raises(ValueError, match="one bond here, bond0"):
        h.apply("bond", "bond1", {"mode": "1", "slaves": ["enp1s0", "enp2s0"]})
    assert h.apply("bond", "bond0", {"mode": "1", "slaves": ["enp1s0", "enp2s0"], "miimon": 100})["status"] == "trial"
    box.a_moment_passes()
    managed.keep(None)
    assert h.apply("bond", "bond0", {"delete": True})["status"] == "trial"


def test_the_port_the_machine_is_reached_on_leads_the_bond(box):
    second_port(box)
    managed.start_bond_trial(["enp1s0", "enp2s0"], "1", 100, now={"interface": "enp2s0"})
    box.a_moment_passes()
    assert "# first: enp2s0" in net(box, "05-kiboto-bond0.netdev")
    assert "MACAddress=52:54:00:12:34:57" in net(box, "05-kiboto-bond0.netdev")
    assert "PrimarySlave=true" in net(box, "05-kiboto-enp2s0.network")
    assert "PrimarySlave" not in net(box, "05-kiboto-enp1s0.network")


def test_a_name_from_a_request_never_leaves_the_networkd_folder(box):
    folder = str(box.root / "network")
    assert managed.file_for("enp1s0.20") == f"{folder}/05-kiboto-enp1s0.20.network"
    for name in ("../etc/passwd", "a/b", "", "..", "x" * 16, "/etc"):
        for make in (managed.file_for, managed.netdev_for, managed.link_for):
            with pytest.raises(ValueError, match="not a network port name"):
                make(name)


def card(box, name="enp1s0"):
    (box.root / "sys" / name / "device").mkdir(exist_ok=True)  # a port of a real network card


def test_wake_on_lan_is_kept_in_the_ports_link_file_and_set_at_once(box):
    card(box)
    answer = managed.set_wake_on_lan("enp1s0", True)
    assert answer == {"status": "ok", "interface": "enp1s0", "wol_enabled": True, "now": True}
    link = net(box, "10-kiboto-enp1s0.link")
    assert "PermanentMACAddress=52:54:00:12:34:56" in link and link.endswith("Name=enp1s0\nWakeOnLan=magic\n")
    assert ["ethtool", "-s", "enp1s0", "wol", "g"] in box.seen
    assert not any(c[0] == "systemd-run" for c in box.seen)  # not a trial: it cannot cut the machine off
    # the pin written at every start keeps it
    assert managed._write_pin("enp1s0") is False and "WakeOnLan=magic" in net(box, "10-kiboto-enp1s0.link")
    managed.set_wake_on_lan("enp1s0", False)
    assert net(box, "10-kiboto-enp1s0.link").endswith("WakeOnLan=off\n")
    assert ["ethtool", "-s", "enp1s0", "wol", "d"] in box.seen


def test_wake_on_lan_needs_a_network_card(box):
    for port, on, said in [
        ("enp1s0", True, "not a port of a network card"),
        ("eth9", True, "not a port"),
        ("enp1s0", "yes", "on or off"),
    ]:
        with pytest.raises(ValueError, match=said):
            managed.set_wake_on_lan(port, on)
    assert net(box, "10-kiboto-enp1s0.link") is None


def test_the_port_dialog_sets_wake_on_lan_and_an_unchanged_size_starts_nothing(box):
    card(box)
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(STATIC)
    h = host.ManagedHostNetwork()
    answer = h.apply("port", "enp1s0", {"wol_enabled": True})
    assert answer["wol_enabled"] is True and "WakeOnLan=magic" in net(box, "10-kiboto-enp1s0.link")
    assert h.apply("port", "enp1s0", {"wol_enabled": True, "mtu": 1500})["changed"] is False
    assert not any(c[0] == "systemd-run" for c in box.seen)


FIXED = {
    "interface": "enp1s0",
    "mode": "static",
    "ip_address": "192.168.1.50",
    "netmask": "255.255.255.0",
    "gateway": "192.168.1.1",
}


def test_ipv6_automatic_off_or_fixed_and_further_routes_go_in_the_ports_file(box):
    auto = managed.network_file(managed.checked(dict(FIXED)))
    assert "IPv6AcceptRA" not in auto and "[Route]" not in auto  # as before: the router's IPv6
    off = managed.network_file(managed.checked({**FIXED, "ipv6_mode": "off"}))
    assert "LinkLocalAddressing=ipv4\nIPv6AcceptRA=no" in off
    dhcp_off = managed.network_file(managed.checked({"interface": "enp1s0", "mode": "dhcp", "ipv6_mode": "off"}))
    assert "DHCP=ipv4" in dhcp_off and "DHCP=yes" not in dhcp_off
    fixed = managed.checked(
        {
            **FIXED,
            "ipv6_mode": "static",
            "ipv6_address": "2001:db8::50/64",
            "ipv6_gateway": "fe80::1",
            "routes": [
                {"destination": "10.20.0.5/16", "gateway": "192.168.1.254"},
                {"destination": "2001:db8:1::/48", "gateway": "2001:db8::1"},
            ],
        }
    )
    text = managed.network_file(fixed)
    assert (
        "Address=192.168.1.50/24\nGateway=192.168.1.1\nAddress=2001:db8::50/64\nGateway=fe80::1\nIPv6AcceptRA=no"
        in text
    )
    assert "[Route]\nDestination=10.20.0.0/16\nGateway=192.168.1.254" in text  # the network, not the host given
    assert "[Route]\nDestination=2001:db8:1::/48\nGateway=2001:db8::1" in text
    # what the dialog reads back is what was written
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(text)
    assert managed.settings_of("enp1s0") == {
        "ipv6_mode": "static",
        "ipv6_address": "2001:db8::50/64",
        "ipv6_gateway": "fe80::1",
        "routes": [
            {"destination": "10.20.0.0/16", "gateway": "192.168.1.254"},
            {"destination": "2001:db8:1::/48", "gateway": "2001:db8::1"},
        ],
    }
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(off)
    assert managed.settings_of("enp1s0")["ipv6_mode"] == "off"


def test_what_ipv6_and_routes_cannot_be(box):
    for extra, said in [
        ({"ipv6_mode": "maybe"}, "automatic IPv6"),
        ({"ipv6_mode": "static", "ipv6_address": "2001:db8::50"}, "prefix length"),
        ({"ipv6_mode": "static", "ipv6_address": "nonsense"}, "prefix length"),
        ({"ipv6_mode": "static", "ipv6_address": "fe80::5/64"}, "cannot be this machine"),
        (
            {"ipv6_mode": "static", "ipv6_address": "2001:db8::50/64", "ipv6_gateway": "2001:db9::1"},
            "not in 2001:db8::/64",
        ),
        ({"ipv6_mode": "static", "ipv6_address": "2001:db8::50/64", "ipv6_gateway": "x"}, "not an IPv6 address"),
        ({"routes": [{"destination": "0.0.0.0/0", "gateway": "192.168.1.254"}]}, "router field above"),
        ({"routes": [{"destination": "10.0.0.0/8", "gateway": "10.0.0.1"}]}, "not in this machine's network"),
        ({"routes": [{"destination": "10.0.0.0/8", "gateway": "2001:db8::1"}]}, "not the same kind"),
        ({"routes": [{"destination": "nope", "gateway": "1.2.3.4"}]}, "not a network and a router"),
        ({"routes": ["10.0.0.0/8"]}, "a network and the router"),
        ({"routes": [{"destination": "10.0.0.0/8", "gateway": "192.168.1.9"}] * 17}, "Up to 16"),
    ]:
        with pytest.raises(ValueError, match=said):
            managed.checked({**FIXED, **extra})


def test_an_address_change_keeps_the_ports_vlans_and_packet_size(box):
    (box.root / "network" / "05-kiboto-enp1s0.network").write_text(STATIC + "VLAN=enp1s0.20\n\n[Link]\nMTUBytes=9000\n")
    managed.start_trial({**FIXED, "ip_address": "192.168.1.60"})
    box.a_moment_passes()
    text = net(box, "05-kiboto-enp1s0.network")
    assert "Address=192.168.1.60/24" in text and "VLAN=enp1s0.20" in text and "MTUBytes=9000" in text
