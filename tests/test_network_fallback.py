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
