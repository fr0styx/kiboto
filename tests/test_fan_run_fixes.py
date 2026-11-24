"""What the real-fan run on 24 Nov 2026 found: a processor spike of a second or two sent the disk
fans to full speed for their whole hold, and NVMe drives around their ceiling stopped and started
the fans every minute or two."""

import types

import pytest

from backend.services import fan_control as fc
from backend.state import Z_STATE


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    clock = types.SimpleNamespace(now=1000.0)
    monkeypatch.setattr(fc, "time", types.SimpleNamespace(time=lambda: clock.now))
    monkeypatch.setattr(fc, "add_event", lambda *a, **k: None)
    Z_STATE.cpu_hot_since = 0.0
    Z_STATE.nvme_fan_hold = False
    Z_STATE.critical_temp_active = False
    Z_STATE.critical_alert_at = 0.0
    yield clock
    Z_STATE.critical_temp_active = False


def test_a_processor_spike_is_not_an_emergency(fresh):
    assert fc._critical_override(87, []) is False  # the first reading at 87 °C
    fresh.now += 2
    assert fc._critical_override(75, []) is False  # back down: it was a spike
    assert Z_STATE.cpu_hot_since == 0.0


def test_a_processor_that_stays_hot_forces_full_speed_and_releases_lower(fresh):
    assert fc._critical_override(82, []) is False
    fresh.now += fc.CPU_SUSTAIN_SECS
    assert fc._critical_override(83, []) is True  # six seconds at 80 °C or more
    fresh.now += 2
    assert fc._critical_override(77, []) is True  # still above 80 - 5 while the override runs
    assert fc._critical_override(74, []) is False


def test_a_hot_drive_needs_no_wait(fresh):
    assert fc._critical_override(50, [{"dev": "sda", "temp": 60}]) is True
    assert fc._critical_override(None, [{"dev": "sda", "temp": 60, "standby": True}]) is False  # asleep: old reading


def test_nvme_drives_let_the_fans_stop_only_well_under_their_ceiling():
    ceiling = 50
    assert fc.nvme_too_warm(45, True, ceiling) is False
    assert fc.nvme_too_warm(50, True, ceiling) is True  # the fans start again
    assert fc.nvme_too_warm(47, True, ceiling) is True  # not yet: they would stop and start again
    assert fc.nvme_too_warm(43, True, ceiling) is True
    assert fc.nvme_too_warm(ceiling - fc.NVME_RELEASE_C, True, ceiling) is False  # cooled down
    assert fc.nvme_too_warm(46, True, ceiling) is False  # warming again, under the ceiling: may stay stopped
    assert fc.nvme_too_warm(None, True, ceiling) is True  # unreadable counts as too warm
    assert fc.nvme_too_warm(None, False, ceiling) is False  # no NVMe drives at all
