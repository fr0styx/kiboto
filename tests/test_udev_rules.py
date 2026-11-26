"""Kiboto OS: a UPS on a USB cable may be used by Kiboto's own user, and nothing else."""

import os
import re

from backend.hardware import ups
from backend.services import udev_rules

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(ROOT, "packaging", "99-kiboto-ups.rules")


def test_only_ups_makers_get_the_group():
    with open(RULES, encoding="utf-8") as f:
        text = f.read()
    vendors = re.findall(
        r'^SUBSYSTEM=="hidraw", ATTRS\{idVendor\}=="([0-9a-f]{4})", GROUP="kiboto", MODE="0660"', text, re.M
    )
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert len(vendors) == len(lines) >= 10  # every rule is one of these, nothing wider
    assert not any("#" in ln for ln in lines)  # udev takes no comment at the end of a rule
    assert set(vendors) <= set(ups.KNOWN_UPS_VENDORS)  # makers Kiboto knows as UPS makers
    for chip_maker in ("04b4", "0001", "048d", "0400", "04d8"):  # used in keyboards and gadgets too
        assert chip_maker not in vendors


def test_the_door_writes_the_rules_once_and_applies_them(tmp_path):
    ran = []
    assert udev_rules.keep_current(ROOT, str(tmp_path), ran.append) == ["99-kiboto-ups.rules"]
    assert ran == [["udevadm", "control", "--reload"], ["udevadm", "trigger", "--subsystem-match=hidraw"]]
    assert (tmp_path / "99-kiboto-ups.rules").stat().st_mode & 0o777 == 0o644
    ran.clear()
    assert udev_rules.keep_current(ROOT, str(tmp_path), ran.append) == [] and ran == []  # nothing again
    assert udev_rules.keep_current(ROOT, str(tmp_path / "none"), ran.append) == []  # no udev here
    assert udev_rules.keep_current(str(tmp_path / "old-release"), str(tmp_path), ran.append) == []
