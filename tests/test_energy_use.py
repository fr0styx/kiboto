"""Re-audit R9: the electricity the UPS feeds, added up per day from its own readings."""

import time

import pytest

from backend.services import energy_use


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(energy_use, "STATE_FILE", str(tmp_path / "energy_use.json"))
    energy_use.reset_for_tests()
    yield
    energy_use.reset_for_tests()


NOON = time.mktime((2026, 11, 19, 12, 0, 0, 0, 0, -1))


def test_readings_add_up_and_only_measured_time_counts():
    for i in range(0, 3601, 60):  # one hour at 60 W
        energy_use.note(60, NOON + i)
    s = energy_use.summary(NOON + 3600)
    assert s["today_kwh"] == pytest.approx(0.06, abs=0.0005)
    assert s["avg_watts"] == pytest.approx(60, abs=0.1) and s["hours_measured"] == 1.0 and s["measuring"]
    # Kiboto was off for three hours: nothing is guessed for the gap
    energy_use.note(60, NOON + 3600 + 3 * 3600)
    energy_use.note(60, NOON + 3600 + 3 * 3600 + 60)
    assert energy_use.summary(NOON + 5 * 3600)["today_kwh"] == pytest.approx(0.061, abs=0.0005)


def test_no_reading_ends_the_stretch_and_nonsense_is_ignored():
    energy_use.note(100, NOON)
    energy_use.note(None, NOON + 30)  # the UPS stopped reporting
    energy_use.note(100, NOON + 60)  # starts a new stretch: the 60 s in between are not counted
    energy_use.note("n/a", NOON + 90)
    energy_use.note(-5, NOON + 100)
    assert energy_use.summary(NOON + 200) == {
        "measuring": False,
        "hours_measured": 0.0,
        "today_kwh": 0.0,
        "week_kwh": 0.0,
        "month_kwh": 0.0,
        "avg_watts": 0.0,
        "price": None,
        "month_cost": None,
    }


def test_days_weeks_and_the_cost_of_a_month():
    for day in range(10):  # ten days, two hours a day at 50 W
        start = NOON - day * 86400
        for i in range(0, 7201, 60):
            energy_use.note(50, start + i)
        energy_use.note(None, start + 7300)
    s = energy_use.summary(NOON + 7200)
    assert s["today_kwh"] == pytest.approx(0.1, abs=0.001)
    assert s["week_kwh"] == pytest.approx(0.7, abs=0.005)
    assert s["month_kwh"] == pytest.approx(1.0, abs=0.005)
    assert s["month_cost"] is None
    assert energy_use.set_price(0.35) == 0.35
    s = energy_use.summary(NOON + 7200)
    assert s["price"] == 0.35 and s["month_cost"] == pytest.approx(50 * 24 * 30 / 1000 * 0.35, abs=0.05)
    assert energy_use.set_price(None) is None and energy_use.summary(NOON)["month_cost"] is None


def test_it_is_kept_across_a_restart_and_old_days_are_dropped(monkeypatch):
    monkeypatch.setattr(energy_use, "KEEP_DAYS", 2)
    for day in (3, 2, 1, 0):
        start = NOON - day * 86400
        energy_use.note(100, start)
        energy_use.note(100, start + 60)
        energy_use.note(None, start + 61)
    energy_use.set_price(0.3)  # saves
    energy_use.reset_for_tests()  # a restart
    s = energy_use.summary(NOON + 100)
    assert s["price"] == 0.3 and s["today_kwh"] > 0
    assert len(energy_use._load()["days"]) == 2


def test_a_data_folder_that_cannot_be_written_does_not_stop_the_readings(monkeypatch):
    def full(*a, **k):
        raise OSError("No space left on device")

    monkeypatch.setattr(energy_use, "atomic_write_json", full)
    energy_use.note(80, NOON)
    energy_use.note(80, NOON + 60)
    assert energy_use.summary(NOON + 60)["today_kwh"] > 0


def test_the_routes(client):
    assert client.get("/api/ups/energy").status_code in (401, 403)
    h = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'password': 'admin'}).json()['token']}"}
    res = client.get("/api/ups/energy", headers=h)
    assert res.status_code == 200 and res.json()["measuring"] is False
    assert client.put("/api/ups/energy/price", headers=h, json={"price": 0.4}).json()["price"] == 0.4
    assert client.put("/api/ups/energy/price", headers=h, json={"price": None}).json()["price"] is None
    assert client.put("/api/ups/energy/price", headers=h, json={"price": -1}).status_code == 422


def test_every_stats_round_passes_the_ups_power_on(monkeypatch):
    from backend.services import stats_collector

    seen = []
    monkeypatch.setattr(energy_use, "note", lambda watts, now=None: seen.append(watts))
    stats_collector._note_energy({"power_watts": 42.5})
    stats_collector._note_energy({})
    stats_collector._note_energy(None)
    assert seen == [42.5, None, None]


def test_a_ups_that_reports_only_a_percentage_can_be_given_its_rated_power(client, monkeypatch):
    from backend.api import ups as ups_api

    saved = {}
    monkeypatch.setattr(ups_api, "read_ups_status", lambda: {"load_pct": 2.0, "power_watts": None})
    monkeypatch.setattr(ups_api, "load_ups_config", lambda: dict(saved))
    monkeypatch.setattr(ups_api, "save_ups_config", lambda cfg: saved.update(cfg) or saved)
    h = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'password': 'admin'}).json()['token']}"}
    view = client.get("/api/ups/energy", headers=h).json()
    assert view["load_only"] is True and view["rated_watts"] is None
    res = client.put("/api/ups/energy/rated-power", headers=h, json={"watts": 900})
    assert res.status_code == 200 and res.json()["rated_watts"] == 900.0 and saved == {"nominal_power_watts": 900.0}
    assert client.put("/api/ups/energy/rated-power", headers=h, json={"watts": None}).json()["rated_watts"] is None
    assert client.put("/api/ups/energy/rated-power", headers=h, json={"watts": 3}).status_code == 422
    # a UPS that gives watts itself needs nothing; one that cannot be read does not break the page
    monkeypatch.setattr(ups_api, "read_ups_status", lambda: {"load_pct": 20.0, "power_watts": 180.0})
    assert client.get("/api/ups/energy", headers=h).json()["load_only"] is False

    def gone():
        raise OSError("no UPS")

    monkeypatch.setattr(ups_api, "read_ups_status", gone)
    view = client.get("/api/ups/energy", headers=h).json()
    assert view["load_only"] is False and view["rated_watts"] is None
