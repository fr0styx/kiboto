"""The address of a machine set up for Kiboto: a trial with a way back."""

import json
import os
import stat

import pytest

from backend import runtime
from backend.hardware.net import host, managed


class Box:
    """The machine: answers systemctl, systemd-run and networkctl, and keeps what was asked."""

    def __init__(self, root):
        self.root, self.seen, self.waiting, self.timer, self.refuse, self.networkd = root, [], [], False, (), True

    def __call__(self, cmd, timeout=20):
        self.seen.append(cmd)
        if cmd[0] in self.refuse:
            return 1, "refused"
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
        self.waiting.append((seconds, what))

    def a_moment_passes(self):
        waiting, self.waiting = self.waiting, []
        for _, what in waiting:
            what()

    def file(self):
        path = self.root / "network" / "05-kiboto-enp1s0.network"
        return path.read_text() if path.exists() else None

    def asked(self, *start):
        return [c for c in self.seen if c[: len(start)] == list(start)]


@pytest.fixture
def box(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    (tmp_path / "network").mkdir()
    for name in ("enp1s0", "docker0", "lo"):
        (tmp_path / "sys" / name).mkdir(parents=True)
    (tmp_path / "sys" / "enp1s0" / "ifindex").write_text("2\n")
    monkeypatch.setattr(managed, "DIR", str(tmp_path / "network"))
    monkeypatch.setattr(managed, "SYS_NET", str(tmp_path / "sys"))
    monkeypatch.setattr(managed, "LEASES", str(tmp_path / "leases"))
    monkeypatch.setattr(managed, "UPSTREAM_DNS", str(tmp_path / "resolv.conf"))
    monkeypatch.setattr(managed, "STATE", str(tmp_path / "data" / "network_trial.json"))
    # root's own copy on a machine Kiboto runs (the tests run as root)
    monkeypatch.setattr(managed, "ROOT_STATE", str(tmp_path / "door" / "network_trial.json"))
    made = Box(tmp_path)
    monkeypatch.setattr(managed, "run", made)
    monkeypatch.setattr(managed, "after", made.later)
    return made


STATIC = {
    "interface": "enp1s0",
    "mode": "static",
    "ip_address": "192.168.1.50",
    "netmask": "255.255.255.0",
    "gateway": "192.168.1.1",
    "dns1": "192.168.1.1",
    "dns2": "1.1.1.1",
}
DHCP = {"interface": "enp1s0", "mode": "dhcp"}


def test_the_file_for_a_fixed_address():
    want = {"iface": "enp1s0", "mode": "static", "address": "192.168.1.50", "prefix": 24, "gateway": "192.168.1.1"}
    text = managed.network_file({**want, "dns": ["192.168.1.1", "1.1.1.1"]})
    assert text.splitlines()[2:] == [
        "[Match]",
        "Name=enp1s0",
        "",
        "[Network]",
        "Address=192.168.1.50/24",
        "Gateway=192.168.1.1",
        "DNS=192.168.1.1",
        "DNS=1.1.1.1",
        "",
        "[IPv6AcceptRA]",
        "UseDNS=no",
    ]
    assert "Gateway" not in managed.network_file({**want, "gateway": "", "dns": []})


def test_the_file_for_an_address_from_the_router():
    want = {"iface": "enp1s0", "mode": "dhcp", "address": "", "prefix": 0, "gateway": ""}
    assert managed.network_file({**want, "dns": []}).splitlines()[5:] == ["[Network]", "DHCP=yes"]
    own = managed.network_file({**want, "dns": ["9.9.9.9"]}).splitlines()[5:]
    assert own == [
        "[Network]",
        "DHCP=yes",
        "DNS=9.9.9.9",
        "",
        "[DHCPv4]",
        "UseDNS=no",
        "",
        "[IPv6AcceptRA]",
        "UseDNS=no",
    ]
    fixed6 = managed.network_file(
        {**want, "dns": ["2606:4700:4700::1111"], "ipv6_mode": "static", "ipv6_address": "2001:db8::5/64"}
    )
    assert "DNS=2606:4700:4700::1111" in fixed6 and "[IPv6AcceptRA]" not in fixed6  # no announcements are taken at all


def test_a_dns_server_may_be_ipv6(box):
    want = managed.checked({**DHCP, "dns1": "2606:4700:4700::1111", "dns2": "1.1.1.1"})
    assert want["dns"] == ["2606:4700:4700::1111", "1.1.1.1"]
    assert managed.checked({**DHCP, "dns1": "2606:4700:4700:0::1111", "dns2": "2606:4700:4700::1111"})["dns"] == [
        "2606:4700:4700::1111"
    ]  # the same server written twice counts once


@pytest.mark.parametrize(
    ("changes", "said"),
    [
        ({**STATIC, "interface": "docker0"}, "not a network port"),
        ({**STATIC, "interface": "lo"}, "not a network port"),
        ({**STATIC, "interface": "eth9"}, "not a network port"),
        ({**STATIC, "interface": "../../etc"}, "not a network port"),
        ({**STATIC, "interface": ""}, "not a network port"),
        ({**STATIC, "mode": "bootp"}, "fixed address or an address from the router"),
        ({**STATIC, "ip_address": ""}, "required"),
        ({**STATIC, "ip_address": "192.168.1.0"}, "network's own address"),
        ({**STATIC, "ip_address": "192.168.1.255"}, "broadcast"),
        ({**STATIC, "ip_address": "127.0.0.1"}, "loopback"),
        ({**STATIC, "gateway": "10.0.0.1"}, "not in the same network"),
        ({**STATIC, "gateway": "192.168.1.50"}, "same as this machine's"),
        ({**STATIC, "netmask": "/4"}, "too wide"),
        ({**STATIC, "netmask": "banana"}, "Invalid netmask"),
        ({**STATIC, "dns1": "one.one.one.one"}, "first DNS server"),
        ({**DHCP, "dns2": "999.1.1.1"}, "second DNS server"),
        ({**DHCP, "dns1": "fe80::1"}, "link-local"),
        ({**DHCP, "dns1": "::1"}, "cannot be ::1"),
        ({**DHCP, "dns1": "ff02::fb"}, "cannot be ff02::fb"),
        ({**DHCP, "dns2": "2001:db8::zz"}, "IPv4 or IPv6 address for The second"),
    ],
)
def test_what_cannot_be_is_refused_with_a_sentence(box, changes, said):
    with pytest.raises(ValueError, match=said):
        managed.checked(changes)


def test_what_was_asked_is_put_in_one_form(box):
    want = managed.checked({**STATIC, "netmask": "24", "dns2": "192.168.1.1", "gateway": "", "timeout_sec": 5})
    assert want == {
        "iface": "enp1s0",
        "mode": "static",
        "address": "192.168.1.50",
        "prefix": 24,
        "gateway": "",
        "dns": ["192.168.1.1"],
        "ipv6_mode": "auto",  # as before: IPv6 from the router, no further routes
        "ipv6_address": "",
        "ipv6_gateway": "",
        "routes": [],
        "timeout": 10,
    }
    assert managed.checked({**DHCP, "timeout_sec": 9999})["timeout"] == 300
    assert managed.checked({**DHCP, "ip_address": "nonsense"})["timeout"] == 60  # not looked at for DHCP
    assert managed.checked({**STATIC, "netmask": "255.255.255.254", "ip_address": "10.0.0.1", "gateway": "10.0.0.0"})


def test_a_guest_reads_its_hosts_network_and_changes_none(tmp_path):
    there = host.current_host()
    assert there.managed is False and not isinstance(there, host.ManagedHostNetwork)
    assert not any(there.capabilities()["can_change"].values())
    with pytest.raises(host.NotOnThisHost):
        there.apply("address", "", STATIC)


def test_a_machine_of_its_own_lets_kiboto_change_the_address_vlans_and_packet_sizes(box):
    there = host.current_host()
    assert isinstance(there, host.ManagedHostNetwork)
    caps = there.capabilities()
    assert caps["managed"] is True and caps["where"] == "debian" and caps["trial"] is None
    assert caps["can_change"] == {
        "address": True,
        "mtu": True,
        "speed": False,
        "wake_on_lan": True,
        "bond": True,
        "bridge": False,
        "vlan": True,
    }
    with pytest.raises(host.NotOnThisHost, match="Debian's own network settings"):
        there.apply("bridge", "br0", {})


def test_a_machine_whose_network_something_else_runs_is_left_alone(box):
    box.networkd = False
    there = host.current_host()
    assert there.capabilities()["can_change"]["address"] is False
    with pytest.raises(host.NotOnThisHost):
        there.apply("address", "", STATIC)
    assert box.file() is None and not box.asked("systemd-run")


def test_the_way_back_is_armed_before_anything_changes(box):
    answer = host.current_host().apply("address", "", STATIC)
    assert answer["status"] == "trial" and answer["interface"] == "enp1s0" and answer["timeout_sec"] == 60
    key = answer["canary_id"]
    assert len(key) >= 32 and answer["url"] == f"http://192.168.1.50:8082/?keep-network={key}"
    assert box.file() is None  # nothing has changed yet
    armed = box.asked("systemd-run")[0]
    assert armed[armed.index("--unit") + 1] == "kiboto-net-revert" and "--on-active=62" in armed
    assert armed[-3:] == ["-m", "backend.hardware.net.managed", "revert"]
    assert key not in " ".join(armed)  # the key is in no command line
    assert stat.S_IMODE(os.stat(managed._record()).st_mode) == 0o600
    assert not box.asked("networkctl")
    box.a_moment_passes()
    assert box.file() == managed.network_file(managed.checked(STATIC))
    assert box.asked("networkctl") == [["networkctl", "reload"], ["networkctl", "reconfigure", "enp1s0"]]


def test_an_address_from_the_router_has_no_link_to_open(box):
    answer = managed.start_trial(DHCP)
    assert answer["url"] == ""
    box.a_moment_passes()
    assert "DHCP=yes" in box.file()
    assert managed.trial_status()["url"] == ""


def test_one_trial_at_a_time(box):
    managed.start_trial(STATIC)
    with pytest.raises(ValueError, match="still being tried"):
        managed.start_trial(DHCP)
    assert len(box.asked("systemd-run")) == 1


def test_keeping_needs_the_trials_own_key_and_stops_the_timer(box):
    key = managed.start_trial(STATIC)["canary_id"]
    box.a_moment_passes()
    with pytest.raises(ValueError, match="not the change being tried"):
        managed.keep("x" * 32)
    assert box.timer is True and os.path.exists(managed._record())
    assert managed.keep(key) == {"status": "ok", "kept": True, "interface": "enp1s0"}
    assert box.timer is False and not os.path.exists(managed._record())
    assert "Address=192.168.1.50/24" in box.file()
    assert managed.keep(key) == {"status": "ok", "kept": False}  # nothing is being tried any more


def test_the_administrator_on_the_page_keeps_without_the_key(box):
    managed.start_trial(STATIC)
    box.a_moment_passes()
    assert host.current_host().apply("address", "", {"confirm": None})["kept"] is True


def test_going_back_from_a_first_change_removes_kibotos_file(box):
    key = managed.start_trial(STATIC)["canary_id"]
    box.a_moment_passes()
    with pytest.raises(ValueError, match="not the change being tried"):
        managed.go_back("y" * 32)
    assert host.current_host().apply("address", "", {"revert": key}) == {
        "status": "ok",
        "reverted": True,
        "interface": "enp1s0",
    }
    assert box.file() is None and box.timer is False and not os.path.exists(managed._record())
    assert box.asked("networkctl", "reconfigure")[-1] == ["networkctl", "reconfigure", "enp1s0"]
    assert managed.go_back(None) == {"status": "ok", "reverted": False}


def test_going_back_from_a_later_change_puts_the_kept_file_back(box):
    managed.keep(managed.start_trial(STATIC)["canary_id"])  # kept before the moment passed: still written
    box.a_moment_passes()
    assert box.file() is None  # a trial that is over changes nothing afterwards
    managed.start_trial(STATIC)
    box.a_moment_passes()
    managed.keep(None)
    kept = box.file()
    managed.start_trial(DHCP)
    box.a_moment_passes()
    assert "DHCP=yes" in box.file()
    managed.go_back(None)
    assert box.file() == kept


def test_a_change_taken_back_at_once_is_never_made(box):
    managed.start_trial(STATIC)
    managed.go_back(None)
    box.a_moment_passes()
    assert box.file() is None and not box.asked("networkctl", "reconfigure")[1:]


def test_without_a_way_back_nothing_is_changed(box):
    box.refuse = ("systemd-run",)
    with pytest.raises(RuntimeError, match="nothing was changed"):
        managed.start_trial(STATIC)
    assert not os.path.exists(managed._record()) and box.waiting == [] and box.file() is None


def test_the_machines_timer_puts_the_settings_back(box):
    managed.start_trial(STATIC)
    box.a_moment_passes()
    assert managed.main(["managed", "revert"]) == 0
    assert box.file() is None and not os.path.exists(managed._record())
    assert not box.asked("systemctl", "stop")  # the timer is that very run
    assert managed.main(["managed"]) == 2 and managed.main(["managed", "keep"]) == 2


def test_a_trial_cut_short_by_a_restart_is_put_back(box, monkeypatch):
    assert managed.settle() is False  # nothing is being tried
    managed.start_trial(STATIC)
    box.a_moment_passes()
    assert managed.settle() is False  # the timer is still running
    box.timer = False  # as a restart of the machine leaves it
    assert managed.settle() is True
    assert box.file() is None and not os.path.exists(managed._record())


def test_a_trial_long_past_its_time_is_put_back_and_does_not_block_the_next(box, monkeypatch):
    managed.start_trial(STATIC)
    box.a_moment_passes()
    later = managed.time.time() + 60 + managed.APPLY_DELAY + managed.GRACE + 1
    monkeypatch.setattr(managed.time, "time", lambda: later)
    assert managed.start_trial(DHCP)["status"] == "trial"  # the old one was settled first
    box.a_moment_passes()
    assert "DHCP=yes" in box.file()


def test_how_the_machine_gets_its_address_now(box, tmp_path):
    assert managed.mode_of("enp1s0") == "static"  # no lease, nothing set in Kiboto
    (tmp_path / "leases").mkdir()
    (tmp_path / "leases" / "2").write_text("ADDRESS=192.168.1.20\n")
    assert managed.mode_of("enp1s0") == "dhcp"
    assert managed.mode_of("eth9") == "dhcp"  # a port that is not there
    managed.keep(managed.start_trial(STATIC)["canary_id"])
    managed.start_trial(STATIC)
    box.a_moment_passes()
    assert managed.mode_of("enp1s0") == "static"  # Kiboto's own file says


def test_the_dns_servers_are_the_ones_asked_not_the_local_stub(box, tmp_path):
    assert managed.dns_servers() == []
    (tmp_path / "resolv.conf").write_text(
        "# made by systemd-resolved\nnameserver 2001:db8::53\nnameserver 192.168.1.1\nnameserver fe80::1%2\n"
        "nameserver fe80::2\nnameserver 1.1.1.1\nnameserver 192.168.1.1\nnameserver nonsense\nsearch lan\n"
    )
    assert managed.dns_servers() == ["192.168.1.1", "1.1.1.1", "2001:db8::53"]  # IPv4 first, no link-local


def test_the_page_is_told_about_a_trial_but_never_its_key(box):
    assert managed.trial_status() is None
    key = managed.start_trial(STATIC)["canary_id"]
    told = managed.trial_status()
    assert told["interface"] == "enp1s0" and 55 <= told["seconds_left"] <= 62
    assert told["url"] == "http://192.168.1.50:8082"
    assert key not in json.dumps(told) and key not in json.dumps(host.current_host().capabilities())


# --- the routes -----------------------------------------------------------------------------------
def test_a_guest_has_no_trial_to_keep(client):
    r = client.post("/api/network/host/keep", json={"canary_id": "k" * 32})
    assert r.status_code == 404


def test_the_address_is_tried_kept_and_shown(box, client, auth_headers):
    r = client.post("/api/network/host/apply", headers=auth_headers, json=STATIC)
    assert r.status_code == 200 and r.json()["status"] == "trial"
    key = r.json()["canary_id"]
    box.a_moment_passes()
    shown = client.get("/api/network/host/config", headers=auth_headers).json()
    assert shown["trial"]["interface"] == "enp1s0" and shown["trial"]["url"] == "http://192.168.1.50:8082"
    assert key not in json.dumps(shown)
    # from the new address nobody is signed in: the key in the link is what keeps it
    assert client.post("/api/network/host/keep", json={"canary_id": "w" * 32}).status_code == 403
    assert client.post("/api/network/host/keep", json={"canary_id": "short"}).status_code == 422
    kept = client.post("/api/network/host/keep", json={"canary_id": key})
    assert kept.status_code == 200 and kept.json()["kept"] is True
    assert client.get("/api/network/host/config", headers=auth_headers).json()["trial"] is None


def test_the_page_that_made_the_change_keeps_it_or_goes_back(box, client, auth_headers):
    client.post("/api/network/host/apply", headers=auth_headers, json=STATIC)
    box.a_moment_passes()
    r = client.post("/api/network/host/revert", headers=auth_headers, json={})
    assert r.status_code == 200 and r.json()["reverted"] is True and box.file() is None
    client.post("/api/network/host/apply", headers=auth_headers, json=DHCP)
    r = client.post("/api/network/host/confirm", headers=auth_headers, json={})
    assert r.status_code == 200 and r.json()["kept"] is True


def test_a_wrong_address_is_said_and_a_machine_that_cannot_is_too(box, client, auth_headers):
    r = client.post("/api/network/host/apply", headers=auth_headers, json={**STATIC, "gateway": "10.9.9.9"})
    assert r.status_code == 400 and "not in the same network" in r.json()["detail"]
    box.refuse = ("systemd-run",)
    r = client.post("/api/network/host/apply", headers=auth_headers, json=STATIC)
    assert r.status_code == 502 and "nothing was changed" in r.json()["detail"]
    assert client.post("/api/network/host/apply", json=STATIC).status_code in (401, 403)
