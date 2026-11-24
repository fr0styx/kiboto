"""When it gets dark where the NAS is, for the look's "By sunset" mode (APP-D)."""

import datetime as dt

from backend.services import sun

TABLE = "# comment\nDE\t+5230+01322\tEurope/Berlin\nAQ\t-7750+16636\tAntarctica/McMurdo\nUS\t+404251-0740023\tAmerica/New_York\n"


def _table(tmp_path):
    path = tmp_path / "zone1970.tab"
    path.write_text(TABLE)
    return (str(path),)


def test_a_zones_place_comes_from_the_zone_table(tmp_path):
    lat, lon = sun.place_of("Europe/Berlin", _table(tmp_path))
    assert round(lat, 2) == 52.5 and round(lon, 2) == 13.37
    lat, lon = sun.place_of("America/New_York", _table(tmp_path))  # seconds and a western longitude
    assert round(lat, 3) == 40.714 and round(lon, 3) == -74.006
    assert sun.place_of("UTC", _table(tmp_path)) is None
    assert sun.place_of("Europe/Berlin", (str(tmp_path / "missing"),)) is None


def _local(ts, zone):
    from zoneinfo import ZoneInfo

    return dt.datetime.fromtimestamp(ts, ZoneInfo(zone)).strftime("%H:%M")


def test_sunrise_and_sunset_are_within_minutes_of_the_almanac():
    rise, set_, polar = sun.sun_times(dt.date(2026, 6, 21), 52.5, 13.37)  # Berlin, midsummer
    assert polar == "" and "04:40" <= _local(rise, "Europe/Berlin") <= "04:48"
    assert "21:30" <= _local(set_, "Europe/Berlin") <= "21:38"
    rise, set_, _ = sun.sun_times(dt.date(2026, 12, 21), 52.5, 13.37)  # midwinter
    assert "08:10" <= _local(rise, "Europe/Berlin") <= "08:20" and "15:50" <= _local(set_, "Europe/Berlin") <= "15:58"


def test_where_the_sun_stays_up_or_down_the_day_says_so():
    assert sun.sun_times(dt.date(2026, 12, 21), -77.83, 166.6) == (None, None, "day")  # McMurdo in December
    assert sun.sun_times(dt.date(2026, 6, 21), -77.83, 166.6) == (None, None, "night")


def test_today_and_tomorrow_in_the_nas_time_zone(tmp_path):
    now = dt.datetime(2026, 11, 24, 22, 0, tzinfo=dt.UTC)
    out = sun.today("Europe/Berlin", now, _table(tmp_path))
    assert out["known"] and [d["date"] for d in out["days"]] == ["2026-11-24", "2026-11-25"]
    assert out["days"][0]["sunrise"] < out["days"][0]["sunset"] < out["days"][1]["sunrise"]
    assert sun.today("UTC", now, _table(tmp_path)) == {"zone": "UTC", "known": False, "days": []}
    assert sun.today("", now, _table(tmp_path))["known"] is False
    assert sun.today("Europe/Nowhere", now, (str(tmp_path / "x"),))["known"] is False


def test_the_page_can_ask(client, auth_headers, monkeypatch):
    monkeypatch.setattr(sun, "zone_now", lambda: "Europe/Berlin")
    r = client.get("/api/system/sun", headers=auth_headers)
    assert r.status_code == 200 and r.json()["zone"] == "Europe/Berlin"
