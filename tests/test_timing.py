"""Jobs set for a time of day are due when their minute has come or just passed: the scheduler
does not look at every minute."""

import time

from backend import timing


def _at(hour, minute, second=0, day=20):
    return time.mktime((2026, 11, day, hour, minute, second, 0, 0, -1))


def test_a_time_of_day_is_due_from_its_minute_until_the_window_ends():
    half_two = _at(2, 30)
    assert timing.moment("02:30", half_two - 1) == 0.0  # not yet
    assert timing.moment("02:30", half_two) == half_two
    assert timing.moment("02:30", _at(2, 31, 3)) == half_two  # the look at 02:30 never came
    assert timing.moment("02:30", half_two + timing.WINDOW - 1) == half_two
    assert timing.moment("02:30", half_two + timing.WINDOW) == 0.0  # a box started later does not catch up
    assert timing.moment("02:30", _at(15, 0)) == 0.0
    assert timing.day_of("02:30", _at(2, 33)) == "2026-11-20" and timing.day_of("02:30", _at(2, 29)) == ""


def test_just_after_midnight_yesterdays_time_still_counts():
    late = _at(23, 58, day=19)
    assert timing.moment("23:58", _at(0, 1)) == late
    assert timing.day_of("23:58", _at(0, 1)) == "2026-11-19"  # the day the job belongs to
    assert timing.moment("23:58", _at(0, 4)) == 0.0


def test_a_time_that_is_none_is_never_due():
    for bad in ("", "soon", "25:00", "02:61", "2", None):
        assert timing.moment(bad, _at(2, 30)) == 0.0, bad
    assert timing.minute_of_hour(60, _at(2, 30)) == 0.0 and timing.minute_of_hour(-1, _at(2, 30)) == 0.0


def test_a_minute_of_the_hour():
    assert timing.minute_of_hour(30, _at(2, 30, 10)) == _at(2, 30)
    assert timing.minute_of_hour(30, _at(2, 32)) == _at(2, 30)
    assert timing.minute_of_hour(30, _at(2, 29, 59)) == 0.0
    assert timing.minute_of_hour(58, _at(3, 1)) == _at(2, 58)  # passed in the hour before
    assert timing.minute_of_hour(58, _at(3, 4)) == 0.0
