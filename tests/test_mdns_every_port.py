"""The name answers on every home network port of a machine Kiboto runs, each with its own address."""

import types

from backend.services import mdns_responder as m


def test_the_home_network_ports_are_found_and_the_rest_left_out():
    ips = {"eth0": "192.168.1.5", "eth1": "10.0.5.2", "lo": "127.0.0.1", "docker0": "172.17.0.1",
           "br-1a2b": "172.18.0.1", "veth9": None, "tailscale0": "100.64.0.3", "kbt0123abcd": None, "wg0": "10.9.0.1",
           "eth2": None, "bond0": "192.168.1.5"}  # fmt: skip
    assert m.lan_ips(list(ips), ips.get) == ["192.168.1.5", "10.0.5.2"]  # once each, up ones only


def test_each_other_port_gets_its_own_answerer(monkeypatch):
    started, sent = [], []

    class Sock:
        def __init__(self, ip):
            self.ip = ip

        def settimeout(self, v):
            pass

        def sendto(self, data, addr):
            sent.append((self.ip, addr))

    class Thread:
        def __init__(self, target, args, daemon, name):
            started.append((name, args[2], args[3]))

        def start(self):
            pass

    import threading

    monkeypatch.setattr(threading, "Thread", Thread)
    monkeypatch.setattr(m, "lan_ips", lambda: ["192.168.1.5", "10.0.5.2", "10.0.9.9"])
    monkeypatch.setattr(m, "smb_open", lambda ip: False)

    def opened(ip):
        if ip == "10.0.9.9":
            raise OSError("no multicast here")
        return Sock(ip)

    monkeypatch.setattr(m, "open_socket", opened)
    args = types.SimpleNamespace(timemachine=[])
    assert m.other_ports("192.168.1.5", args, ["kbtest"], "Kiboto", 8082) == ["10.0.5.2"]
    assert started == [("mdns-10.0.5.2", "10.0.5.2", False)]  # its own address, not followed
    assert sent == [("10.0.5.2", (m.GROUP, m.PORT))]  # announced on that port


def test_the_responder_starts_again_when_the_ports_change(monkeypatch):
    class Sock:
        def settimeout(self, v):
            pass

        def recvfrom(self, n):
            raise OSError("timed out")

    times = iter([0.0, 100.0, 200.0])
    monkeypatch.setattr(m, "current_ip", lambda: "192.168.1.5")
    monkeypatch.setattr(m, "lan_ips", lambda: ["192.168.1.5", "10.0.5.2"])
    r = types.SimpleNamespace(reply=lambda data, port: b"")
    code = m.serve(Sock(), r, "192.168.1.5", True, clock=lambda: next(times), ports=["192.168.1.5"])
    assert code == m.ADDRESS_CHANGED


def test_an_interface_address_is_read_from_the_kernel():
    assert m._if_ip("lo") == "127.0.0.1"
    assert m._if_ip("no-such-port0") is None
    assert "127.0.0.1" not in m.lan_ips()
