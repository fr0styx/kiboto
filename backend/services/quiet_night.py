"""Quieter at night (hardware report, the optional extras; owner 18 Nov: build it, off by default).

Between two times the automatic fan curve reads the drives as a few degrees cooler than they are, so
the fans turn a little slower while the household sleeps. The shift fades out between 45 and 50 °C:
a warm drive gets the normal curve. Nothing else changes: the full-speed override at 55 °C (NVMe 75 °C,
the processor near its limit), the NVMe and processor fans, fan stop and the fixed modes are as they were. It only
acts in the Automatic mode, and only once turned on.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from typing import Any

from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, read_json, read_json_cached

SETTINGS_FILE = os.path.join(DATA_DIR, "quiet_night.json")
SHIFT_C = 4.0
FULL_SHIFT_BELOW_C = 45.0
NO_SHIFT_FROM_C = 50.0
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def state() -> dict[str, Any]:
    saved = read_json(SETTINGS_FILE, {}) or {}
    return {
        "enabled": bool(saved.get("enabled", False)),
        "start": saved.get("start") if _TIME.match(str(saved.get("start", ""))) else "23:00",
        "end": saved.get("end") if _TIME.match(str(saved.get("end", ""))) else "07:00",
    }


def public_state(now: dt.datetime | None = None) -> dict[str, Any]:
    st = state()
    return {**st, "shift_c": SHIFT_C, "warm_c": NO_SHIFT_FROM_C, "active_now": active(now, st)}


def save(enabled: bool, start: str, end: str) -> dict[str, Any]:
    from backend.errors import SaidError

    if not (_TIME.match(start or "") and _TIME.match(end or "")):
        raise SaidError("Use times like 23:00 and 07:00.", "qn_times")
    if start == end:
        raise SaidError("The start and end times must differ.", "qn_same_times")
    atomic_write_json(SETTINGS_FILE, {"enabled": bool(enabled), "start": start, "end": end})
    return public_state()


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_window(now: dt.datetime, start: str, end: str) -> bool:
    """Whether `now` falls between start and end; a window may run past midnight (23:00 to 07:00)."""
    t, a, b = now.hour * 60 + now.minute, _minutes(start), _minutes(end)
    return a <= t < b if a < b else (t >= a or t < b)


def active(now: dt.datetime | None = None, st: dict[str, Any] | None = None) -> bool:
    if st is None:
        saved = read_json_cached(SETTINGS_FILE, {}) or {}  # the fan loop asks every two seconds
        if not saved.get("enabled"):
            return False
        st = {**state(), **{k: saved[k] for k in ("start", "end") if _TIME.match(str(saved.get(k, "")))}}
    if not st.get("enabled"):
        return False
    return in_window(now or dt.datetime.now(), st["start"], st["end"])


def shift_for(temp: float) -> float:
    """Full shift below 45 °C, none from 50 °C, in between in proportion."""
    if temp <= FULL_SHIFT_BELOW_C:
        return SHIFT_C
    if temp >= NO_SHIFT_FROM_C:
        return 0.0
    return SHIFT_C * (NO_SHIFT_FROM_C - temp) / (NO_SHIFT_FROM_C - FULL_SHIFT_BELOW_C)


def curve_temp(temp: float, now: dt.datetime | None = None) -> float:
    """The temperature the drive fans' curve is read at: lower at night when this is on."""
    return temp - shift_for(temp) if active(now) else temp
