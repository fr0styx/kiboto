"""Sign-in hours as two rows, school days and weekends (SET-19 stage 5, Users decision 5 b)."""

from datetime import datetime

import pytest

from backend import signin_hours as sh

TWO = {
    "rows": [
        {"days": [4, 0, 1, 2, 3], "start": "07:00", "end": "20:00"},
        {"days": [6, 5], "start": "09:00", "end": "22:00"},
    ]
}
MON = datetime(2026, 11, 2)  # a Monday
SAT = datetime(2026, 11, 7)


def test_two_rows_are_kept_and_one_row_is_the_old_form():
    assert sh.normalize(TWO) == {
        "rows": [
            {"days": [0, 1, 2, 3, 4], "start": "07:00", "end": "20:00"},
            {"days": [5, 6], "start": "09:00", "end": "22:00"},
        ]
    }
    one = {"rows": [{"days": [0, 1, 2, 3, 4, 5, 6], "start": "07:00", "end": "21:00"}]}
    assert sh.normalize(one) == {"days": [0, 1, 2, 3, 4, 5, 6], "start": "07:00", "end": "21:00"}
    assert sh.from_json('{"rows": [{"days": [5, 6], "start": "09:00", "end": "22:00"}]}')["days"] == [5, 6]


@pytest.mark.parametrize(
    "bad",
    [
        {"rows": []},
        {
            "rows": [
                {"days": [0, 1], "start": "07:00", "end": "20:00"},
                {"days": [1, 5], "start": "09:00", "end": "22:00"},
            ]
        },
        {"rows": [{"days": [0], "start": "07:00", "end": "07:00"}]},
        {"rows": ["weekdays"]},
    ],
)
def test_bad_rows_are_refused(bad):
    with pytest.raises(ValueError):
        sh.normalize(bad)


def test_each_row_has_its_own_times():
    hours = sh.normalize(TWO)
    assert sh.allowed(hours, MON.replace(hour=7)) and not sh.allowed(hours, MON.replace(hour=21))
    assert not sh.allowed(hours, SAT.replace(hour=8)) and sh.allowed(hours, SAT.replace(hour=21))
    assert sh.row_for(hours, SAT)["start"] == "09:00" and sh.row_for(hours, MON)["start"] == "07:00"
    assert sh.describe(hours) == "Mon-Fri 07:00-20:00; Sat, Sun 09:00-22:00"


def test_a_late_friday_runs_into_saturday_morning():
    hours = sh.normalize(
        {"rows": [{"days": [4], "start": "21:00", "end": "01:00"}, {"days": [5, 6], "start": "10:00", "end": "18:00"}]}
    )
    assert sh.allowed(hours, SAT.replace(hour=0, minute=30))
    assert not sh.allowed(hours, SAT.replace(hour=9))


def test_outside_two_row_hours_the_sign_in_names_todays(client, monkeypatch):
    from backend import users_db

    user = users_db.create_user("rowkid", "Row Kid", "a-Long-unique-pw-91", role_id="kid")
    users_db.update_user_profile(user["id"], signin_hours=sh.normalize(TWO))
    monkeypatch.setattr(sh, "allowed", lambda hours, now=None: False)
    monkeypatch.setattr(sh, "row_for", lambda hours, now=None: hours["rows"][1])
    r = client.post("/api/auth/login", json={"username": "rowkid", "password": "a-Long-unique-pw-91"})
    assert r.status_code == 403
    said = r.json()["text"]  # in the person's language: a key and its values (SET-11)
    assert r.json()["error"] == "outside_signin_hours" and said["params"]["start"] == "09:00"
    assert said["params"]["days"] == {"weekdays": [5, 6]}
