"""Jobs that run at a time of day.

The scheduler looks about once a minute, and each look comes a moment later than the one before
(a look takes time). So now and then a minute is never looked at, and a job that waits for "the
clock reads 02:30" is skipped that day without a word. A job is due instead when its time has
come, or passed by no more than WINDOW seconds, and it has not run for that time yet.

WINDOW is short on purpose: a NAS that was off at 02:30 and starts at 15:00 does not run the
night's jobs in the afternoon.
"""

from __future__ import annotations

import time

WINDOW = 300.0


def moment(at: str, now: float, window: float = WINDOW) -> float:
    """When the time of day `at` ("HH:MM") last came, if that is now or up to `window` seconds
    ago; else 0. Just after midnight, yesterday's 23:58 still counts."""
    try:
        hour, minute = (int(part) for part in at.split(":"))
    except (ValueError, AttributeError):
        return 0.0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return 0.0
    for back in (0, 86400):
        t = time.localtime(now - back)
        came = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, hour, minute, 0, 0, 0, -1))
        if 0 <= now - came < window:
            return came
    return 0.0


def day_of(at: str, now: float, window: float = WINDOW) -> str:
    """The day ("YYYY-MM-DD") whose `at` is due now, or "" when it is not."""
    came = moment(at, now, window)
    return time.strftime("%Y-%m-%d", time.localtime(came)) if came else ""


def minute_of_hour(minute: int, now: float, window: float = WINDOW) -> float:
    """When minute `minute` of an hour last came, if that is now or up to `window` seconds ago; else 0."""
    if not 0 <= minute <= 59:
        return 0.0
    t = time.localtime(now)
    came = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, minute, 0, 0, 0, -1))
    if came > now:
        came -= 3600
    return came if 0 <= now - came < window else 0.0
