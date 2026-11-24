"""A wired port no file names still gets an address, so the machine can be reached after its network
card moved to another slot or was replaced."""

import os
import pathlib

from backend.hardware.net import managed

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Machine:
    def __init__(self, networkd=True):
        self.networkd, self.seen = networkd, []

    def __call__(self, cmd, timeout=20):
        self.seen.append(cmd)
        if cmd[:2] == ["systemctl", "is-active"]:
            return 0, "active\nactive" if self.networkd else "inactive\nactive"
        return 0, ""


def test_the_fallback_is_written_once(tmp_path, monkeypatch):
    monkeypatch.setattr(managed, "DIR", str(tmp_path))
    monkeypatch.setattr(managed, "FALLBACK", str(tmp_path / "99-kiboto-any-wired.network"))
    do = Machine()
    assert managed.ensure_fallback(do) is True
    text = (tmp_path / "99-kiboto-any-wired.network").read_text()
    assert "Type=ether" in text and "Kind=!*" in text and "RouteMetric=2048" in text
    assert ["networkctl", "reload"] in do.seen
    assert managed.ensure_fallback(do) is False  # the same file: left alone
    (tmp_path / "99-kiboto-any-wired.network").write_text("changed by hand")
    assert managed.ensure_fallback(do) is True
    assert managed.ensure_fallback(Machine(networkd=False)) is False


def test_install_writes_the_same_file():
    script = (ROOT / "packaging" / "install.sh").read_text()
    body = script.split("<<'ANY'\n", 1)[1].split("\nANY", 1)[0] + "\n"
    assert body == managed.FALLBACK_TEXT
    assert os.path.basename(managed.FALLBACK) in script


MAC = "52:54:00:12:34:56"


def _card(sys_net, name, mac=MAC, device=True):
    port = sys_net / name
    port.mkdir(parents=True)
    (port / "address").write_text(mac + "\n")
    if device:
        (port / "device").mkdir()


def test_a_cards_port_keeps_its_name_in_any_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(managed, "DIR", str(tmp_path / "network"))
    monkeypatch.setattr(managed, "SYS_NET", str(tmp_path / "sys"))
    _card(tmp_path / "sys", "enp0s9")
    _card(tmp_path / "sys", "enp3s0", mac="52:54:00:aa:bb:cc")
    _card(tmp_path / "sys", "br0", device=False)  # a bridge carries a card's address but has no card
    do = Machine()
    assert managed.pin(["enp0s9", "enp3s0", "br0", "../x"], do) == ["enp0s9", "enp3s0"]
    text = (tmp_path / "network" / "10-kiboto-enp0s9.link").read_text()
    assert f"PermanentMACAddress={MAC}" in text and "\nName=enp0s9\n" in text
    assert not (tmp_path / "network" / "10-kiboto-br0.link").exists()
    assert do.seen.count(["update-initramfs", "-u"]) == 1  # the start-up image once for both
    do.seen.clear()
    assert managed.pin(["enp0s9"], do) == [] and do.seen == []  # the same pin: nothing again


def test_ports_with_kibotos_settings_are_pinned_at_start(tmp_path, monkeypatch):
    monkeypatch.setattr(managed, "DIR", str(tmp_path / "network"))
    monkeypatch.setattr(managed, "FALLBACK", str(tmp_path / "network" / "99-kiboto-any-wired.network"))
    monkeypatch.setattr(managed, "SYS_NET", str(tmp_path / "sys"))
    (tmp_path / "network").mkdir()
    (tmp_path / "network" / "05-kiboto-enp0s9.network").write_text("[Match]\nName=enp0s9\n")
    _card(tmp_path / "sys", "enp0s9")
    do = Machine()
    managed.ensure_fallback(do)
    assert (tmp_path / "network" / "10-kiboto-enp0s9.link").exists()

    def refuses(cmd, timeout=20):
        return (1, "update-initramfs: failed") if cmd[0] == "update-initramfs" else do(cmd, timeout)

    (tmp_path / "network" / "10-kiboto-enp0s9.link").unlink()
    assert managed.ensure_pins(refuses) == ["enp0s9"]  # the pin is written; the failure is only said


def test_a_port_given_settings_is_pinned_and_a_bridge_is_not(tmp_path, monkeypatch):
    monkeypatch.setattr(managed, "DIR", str(tmp_path / "network"))
    monkeypatch.setattr(managed, "SYS_NET", str(tmp_path / "sys"))
    _card(tmp_path / "sys", "enp0s9")
    do = Machine()
    managed._write_files(
        {managed.file_for("enp0s9"): "[Match]\nName=enp0s9\n", managed.file_for("br0"): None}, ["enp0s9", "br0"], do
    )
    assert (tmp_path / "network" / "10-kiboto-enp0s9.link").exists()
    assert not (tmp_path / "network" / "10-kiboto-br0.link").exists()


def test_install_pins_the_port_with_the_same_file():
    script = (ROOT / "packaging" / "install.sh").read_text()
    fmt = script.split("printf '# Written by Kiboto: the network card ", 1)[1].split("' \\\n", 1)[0]
    made = ("# Written by Kiboto: the network card " + fmt).replace("\\n", "\n")
    for value in (MAC, "enp0s9", MAC, "enp0s9"):
        made = made.replace("%s", value, 1)
    assert made == managed.pin_text("enp0s9", MAC)
    assert 'rm -f "$file" "/etc/systemd/network/10-kiboto-$iface.link"' in script  # the way back takes it too
