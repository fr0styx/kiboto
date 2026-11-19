"""The Prometheus page carries the UPS's power and the electricity totals of the Power page."""

import pytest

from backend.api import metrics
from backend.services import energy_use
from backend.state import Z_STATE


@pytest.fixture
def page(monkeypatch, tmp_path):
    monkeypatch.setattr(energy_use, "STATE_FILE", str(tmp_path / "energy.json"))
    energy_use.reset_for_tests()

    def read(ups):
        monkeypatch.setattr(Z_STATE, "cached_stats", {"cpu": {"temp": 40, "util": 5}, "ups": ups})
        text = metrics.prometheus_metrics()
        return {
            line.split(" ")[0]: float(line.split(" ")[1]) for line in text.splitlines() if line.startswith("kiboto_")
        }

    yield read
    energy_use.reset_for_tests()


def test_nothing_about_electricity_before_it_is_measured(page):
    seen = page({"available": True, "load_pct": 12, "power_watts": None})
    assert "kiboto_ups_power_watts" not in seen and not [k for k in seen if k.startswith("kiboto_energy_")]
    assert seen["kiboto_ups_load_percent"] == 12.0


def test_power_and_totals_once_measured(page, monkeypatch):
    now = 1_800_000_000.0
    for i in range(0, 7201, 60):  # two hours at 90 W
        energy_use.note(90, now=now + i)
    monkeypatch.setattr(energy_use.time, "time", lambda: now + 7200)
    seen = page({"available": True, "load_pct": 10, "power_watts": 90})
    assert seen["kiboto_ups_power_watts"] == 90.0
    assert seen["kiboto_energy_average_watts"] == 90.0
    assert seen["kiboto_energy_30d_kwh"] == pytest.approx(0.18, abs=0.002)
    assert seen["kiboto_energy_7d_kwh"] == seen["kiboto_energy_30d_kwh"] >= seen["kiboto_energy_today_kwh"]
    assert seen["kiboto_energy_total_kwh"] == pytest.approx(0.18, abs=0.002)
    # no UPS now: the power gauge goes, the totals of what was measured stay
    seen = page({"available": False})
    assert "kiboto_ups_power_watts" not in seen and seen["kiboto_energy_30d_kwh"] > 0


def test_totals_that_cannot_be_read_leave_the_page_whole(page, monkeypatch):
    def gone():
        raise OSError("unreadable")

    monkeypatch.setattr(energy_use, "summary", gone)
    seen = page({"available": True, "load_pct": 10, "power_watts": 50})
    assert seen["kiboto_ups_power_watts"] == 50.0 and "kiboto_cpu_temp_celsius" in seen
