"""How much electricity the NAS uses (re-audit 19 Nov 2026, R9).

A UPS that reports its load says how many watts go through it right now. Kiboto adds those
readings up per day: what the UPS feeds (this NAS and anything else plugged into it) today, in
the last 7 and 30 days, the average, and, with a price per kWh, what a month costs. Without a
UPS that reports its power there is nothing to add up, and the page says so.

Only time that was really measured is counted: a gap (Kiboto was off, the UPS was silent) adds
nothing, so the totals are never guessed.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, read_json
from backend.ignored_errors import ignored

STATE_FILE = os.path.join(DATA_DIR, "energy_use.json")
MAX_GAP_SECS = 120.0  # readings further apart are not joined: nobody measured in between
SAVE_EVERY_SECS = 300.0
KEEP_DAYS = 400

_lock = threading.Lock()
_state: dict[str, Any] | None = None
_last_at: float | None = None
_saved_at = 0.0


def _load() -> dict[str, Any]:
    global _state
    if _state is None:
        data = read_json(STATE_FILE, {})
        data = data if isinstance(data, dict) else {}
        kept = data.get("days")
        days: dict[str, Any] = kept if isinstance(kept, dict) else {}
        total = data.get("total_wh")
        if not isinstance(total, (int, float)) or isinstance(total, bool):
            # kept since before the counter: it starts at what the days on record add up to
            total = sum(float(d[0]) for d in days.values() if isinstance(d, list) and d)
        _state = {"days": days, "price": data.get("price"), "total_wh": round(float(total), 4)}
    return _state


def _day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now))


def _save(now: float) -> None:
    global _saved_at
    st = _load()
    for old in sorted(st["days"])[:-KEEP_DAYS]:
        del st["days"][old]
    atomic_write_json(STATE_FILE, st)
    _saved_at = now


def note(power_watts: Any, now: float | None = None) -> None:
    """One reading of the UPS's power. Called with every stats round; never raises."""
    global _last_at
    now = time.time() if now is None else now
    try:
        watts = float(power_watts)
    except (TypeError, ValueError):
        watts = 0.0
    with _lock:
        if watts <= 0:
            _last_at = None  # no reading: the next one starts a new stretch
            return
        st = _load()
        if _last_at is not None and 0 < now - _last_at <= MAX_GAP_SECS:
            dt = now - _last_at
            day = st["days"].setdefault(_day(now), [0.0, 0.0])
            day[0] = round(day[0] + watts * dt / 3600.0, 4)  # watt-hours
            # everything ever measured: it only grows, while the days fall off after KEEP_DAYS
            st["total_wh"] = round(st["total_wh"] + watts * dt / 3600.0, 4)
            day[1] = round(day[1] + dt, 1)  # seconds measured
        _last_at = now
        if now - _saved_at >= SAVE_EVERY_SECS:
            try:
                _save(now)
            except OSError:
                # a full or read-only data folder must not stop the stats round
                ignored("backend.services.energy_use.note")


def set_price(price: float | None) -> float | None:
    with _lock:
        st = _load()
        st["price"] = round(float(price), 4) if price else None
        _save(time.time())
        return st["price"]


def summary(now: float | None = None) -> dict[str, Any]:
    """Today, the last 7 and 30 days in kWh, the average watts, and the cost of a month."""
    now = time.time() if now is None else now
    with _lock:
        st = _load()
        days = dict(st["days"])
        price = st.get("price")
        total_wh = float(st.get("total_wh") or 0.0)
    keys = [_day(now - i * 86400) for i in range(30)]

    def total(n: int) -> float:
        return sum(float(days.get(k, [0, 0])[0]) for k in keys[:n])

    secs = sum(float(days.get(k, [0, 0])[1]) for k in keys)
    month_wh = total(30)
    avg_watts = month_wh / (secs / 3600.0) if secs >= 60 else 0.0
    return {
        "measuring": secs >= 60,
        "hours_measured": round(secs / 3600.0, 1),
        "today_kwh": round(total(1) / 1000.0, 3),
        "week_kwh": round(total(7) / 1000.0, 3),
        "month_kwh": round(month_wh / 1000.0, 3),
        "total_kwh": round(total_wh / 1000.0, 3),
        "avg_watts": round(avg_watts, 1),
        "price": price,
        # a month at the measured average, so a new install has an answer after its first hours
        "month_cost": round(avg_watts * 24 * 30 / 1000.0 * float(price), 2) if price and avg_watts else None,
    }


def reset_for_tests() -> None:
    global _state, _last_at, _saved_at
    with _lock:
        _state, _last_at, _saved_at = None, None, 0.0
