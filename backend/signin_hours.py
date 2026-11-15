"""When a family account may be signed in (COMP-13).

An administrator can give a kid's or guest's account sign-in hours, for example Monday to
Friday 07:00-20:00. Outside them the person can't sign in, and a session that is open stops
working until the hours start again. Times are the server's time zone (Settings → Time).
A span that ends before it starts runs past midnight (21:00-01:00). Accounts that can manage
people can't be limited, so nobody locks the household out.

Since SET-19 stage 5 (Users decision 5 b) the hours can be two rows, school days and weekends, each
with its own times: {"rows": [{"days": [0..4], ...}, {"days": [5, 6], ...}]}. One row is stored in the
older flat form, so hours set before keep their shape and meaning.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _minutes(value: str) -> int:
    m = _TIME.match(str(value or "").strip())
    if not m:
        raise ValueError("Times are HH:MM, for example 07:30.")
    return int(m.group(1)) * 60 + int(m.group(2))


def _row(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Sign-in hours are days with a start and an end time.")
    days = sorted({int(d) for d in value.get("days") or [] if str(d).lstrip("-").isdigit()})
    if not days or any(d < 0 or d > 6 for d in days):
        raise ValueError("Choose at least one day for the sign-in hours.")
    start, end = str(value.get("start", "")).strip(), str(value.get("end", "")).strip()
    if _minutes(start) == _minutes(end):
        raise ValueError("The sign-in hours need different start and end times.")
    return {"days": days, "start": start, "end": end}


def normalize(value: Any) -> dict[str, Any] | None:
    """{"days": [0..6, Monday is 0], "start": "HH:MM", "end": "HH:MM"}, or {"rows": [two of those]}
    for school days and weekends with their own times; None for no limit."""
    if not value:
        return None
    if not isinstance(value, dict):
        raise ValueError("Sign-in hours are days with a start and an end time.")
    if "rows" not in value:
        return _row(value)
    rows = [_row(r) for r in value.get("rows") or []]
    if not rows:
        raise ValueError("Choose at least one day for the sign-in hours.")
    seen: set[int] = set()
    for r in rows:
        if seen & set(r["days"]):
            raise ValueError("A day can be in only one row of the sign-in hours.")
        seen |= set(r["days"])
    return rows[0] if len(rows) == 1 else {"rows": rows}


def rows_of(hours: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows of stored hours, the flat form as one row."""
    return list(hours["rows"]) if "rows" in hours else [hours]


def row_for(hours: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """The row that covers today, else the first: what "you can sign in ..." names."""
    day = (now or datetime.now()).weekday()
    rows = rows_of(hours)
    return next((r for r in rows if day in r["days"]), rows[0])


def from_json(text: Any) -> dict[str, Any] | None:
    """The stored form back; anything unreadable counts as no limit being set."""
    if not text:
        return None
    try:
        return normalize(json.loads(text) if isinstance(text, str) else text)
    except (ValueError, TypeError):
        return None


def allowed(hours: dict[str, Any] | None, now: datetime | None = None) -> bool:
    if not hours:
        return True
    now = now or datetime.now()
    return any(_row_allows(r, now) for r in rows_of(hours))


def _row_allows(hours: dict[str, Any], now: datetime) -> bool:
    t = now.hour * 60 + now.minute
    s, e = _minutes(hours["start"]), _minutes(hours["end"])
    day, days = now.weekday(), set(hours["days"])
    if s < e:
        return day in days and s <= t < e
    # past midnight: the evening part on a chosen day, the morning part on the day after one
    return (day in days and t >= s) or ((day - 1) % 7 in days and t < e)


def describe(hours: dict[str, Any] | None) -> str:
    """'Mon-Fri 07:00-20:00; Sat-Sun 09:00-21:00' (English; the web UI shows its own wording)."""
    if not hours:
        return ""
    return "; ".join(_describe_row(r) for r in rows_of(hours))


def _describe_row(hours: dict[str, Any]) -> str:
    days = hours["days"]
    if days == list(range(7)):
        when = "every day"
    elif len(days) > 2 and days == list(range(days[0], days[-1] + 1)):
        when = f"{DAY_NAMES[days[0]]}-{DAY_NAMES[days[-1]]}"
    else:
        when = ", ".join(DAY_NAMES[d] for d in days)
    return f"{when} {hours['start']}-{hours['end']}"
