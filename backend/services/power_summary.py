"""Power, the whole answer in one place (SET-31, Power stage 3; owner: rebuild in stages).

The Power page asked four routes and worked the state out itself, so the top bar, the page and
Overview could disagree. This module says, from one reading: the state in one word and its reason,
up to three numbers, the four checks behind "Protected", who switches the NAS off, whether it
starts again by itself, the last battery test and practice run, the last power events, and what
the page may offer. The page turns the words into sentences in the reader's language.

States: none (no UPS found), unreadable (found, cannot be read), protected (on mains, every check
passes), look (on mains, a check fails: the reason names which), cut (on battery), shutting (the
battery is nearly empty and Kiboto is shutting the NAS down), by_hand (nearly empty and nothing
can switch the NAS off), silent (the UPS stopped answering during a power cut).
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

from backend.config import DATA_DIR
from backend.fsutil import read_json
from backend.hardware import ups_state

COMES_BACK_FILE = os.path.join(DATA_DIR, "power_comes_back.json")
HISTORY_ROWS = 5
LOOK_BACK_ROWS = 50  # how far back the last battery test is looked for


def _words(status: Any) -> set[str]:
    return {w for w in re.split(r"[^A-Z0-9]+", str(status or "").upper()) if w}


def checks(ups: dict[str, Any], path: dict[str, Any]) -> list[dict[str, Any]]:
    """The four checks behind "Protected", in the order the page names a failing one."""
    readable = bool(ups.get("available")) and not ups.get("unreadable") and not ups.get("permission_error")
    words = _words(ups.get("status"))
    battery_ok = "RB" not in words and not (ups.get("battery_low") and not ups.get("on_battery"))
    blind = ups.get("battery_charge_pct") is None and ups.get("time_left_min") is None
    return [
        {"id": "readable", "ok": readable},
        {"id": "switch_off", "ok": bool(path.get("ok"))},
        {"id": "battery", "ok": battery_ok, "replace": "RB" in words},
        # a UPS that reports neither runtime nor charge falls back to the set time, so the rule
        # always fires; the page says which limit it uses
        {"id": "rule", "ok": True, "blind": blind},
    ]


def state_of(ups: dict[str, Any], path: dict[str, Any], outage: dict[str, Any], cfg: dict[str, Any]) -> tuple[str, str]:
    """(state, reason) from one reading, the shutdown path and the watchdog's view of an outage."""
    if outage.get("silent"):
        return "silent", ""
    if ups.get("permission_error") or ups.get("unreadable"):
        return "unreadable", "permission" if ups.get("permission_error") else ""
    if not ups.get("available"):
        return "none", ""
    if ups.get("on_battery"):
        elapsed = time.time() - outage["since"] if outage.get("since") else 0.0
        low = outage.get("failsafe") or (
            ups_state.shutdown_reason(
                ups.get("status"), ups.get("battery_charge_pct"), ups.get("time_left_min"), elapsed, cfg
            )
            is not None
        )
        if low:
            return ("shutting", "") if path.get("ok") else ("by_hand", "")
        return "cut", ""
    failing = [c for c in checks(ups, path) if not c["ok"]]
    if failing:
        return "look", failing[0]["id"]
    return "protected", ""


def comes_back(owner: str) -> dict[str, Any]:
    """Will the NAS start again by itself after a power cut? Proven only after a real one (Power
    decision 6); on Unraid and TrueNAS the host decides."""
    from backend.services.ups_watchdog import HOST_OWNED

    if owner in HOST_OWNED:
        return {"answer": "host", "host": HOST_OWNED[owner]}
    rec = read_json(COMES_BACK_FILE, {}) or {}
    if isinstance(rec, dict) and rec.get("proven_at"):
        return {"answer": "proven", "at": rec["proven_at"]}
    if isinstance(rec, dict) and rec.get("failed_at"):
        return {"answer": "no", "at": rec["failed_at"]}
    return {"answer": "not_proven"}


_path_cache: dict[str, Any] = {"at": 0.0, "value": None}
PATH_FRESH_SECS = 60.0


def _path(report) -> dict[str, Any]:
    """Who switches the NAS off, asked at most once a minute (it may probe the host's UPS service)."""
    now = time.monotonic()
    value: dict[str, Any] | None = _path_cache["value"]
    if value is None or now - _path_cache["at"] > PATH_FRESH_SECS:
        value = report()
        _path_cache.update(at=now, value=value)
    return value or {}


def summary(
    ups: dict[str, Any] | None = None,
    path: dict[str, Any] | None = None,
    outage: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Everything the Power page shows, from one reading."""
    from backend.db import query_ups_events
    from backend.hardware.ups import load_ups_config, read_ups_status
    from backend.services import ups_watchdog

    ups = ups if ups is not None else read_ups_status(reprobe=True)
    path = path if path is not None else _path(ups_watchdog.shutdown_path_report)
    outage = outage if outage is not None else ups_watchdog.outage_view()
    cfg = cfg if cfg is not None else load_ups_config()
    events = events if events is not None else query_ups_events(limit=LOOK_BACK_ROWS)
    battery = next((e for e in events if e.get("event_type") == "SELF_TEST"), None)
    state, reason = state_of(ups, path, outage, cfg)
    mode = str(ups.get("mode") or cfg.get("mode") or "")
    over_nut = "nut" in mode or "nut" in str(ups.get("protocol") or "").lower()
    watts = ups.get("power_watts") if ups.get("nominal_power_watts") else None
    return {
        "state": state,
        "reason": reason,
        "numbers": {
            "battery_pct": ups.get("battery_charge_pct"),
            "minutes": ups.get("time_left_min"),
            "watts": watts,
        },
        "since": outage.get("since"),
        "drill": bool(outage.get("drill")),
        "checks": checks(ups, path),
        "switch_off": {
            "by": path.get("by"),
            "ok": bool(path.get("ok")),
            "text": path.get("text"),
            "detail": path.get("detail"),
        },
        "rule": {
            "policy": cfg.get("shutdown_policy", "runtime_left"),
            "minutes": cfg.get("runtime_threshold_min", 5),
            "battery_pct": cfg.get("battery_threshold_pct", 20),
            "timer_sec": cfg.get("shutdown_timer_sec", 300),
        },
        "comes_back": comes_back(str(path.get("by") or "kiboto")),
        "tests": {
            "practice": ups_watchdog.last_practice() or None,
            "battery": {"at": battery.get("ts"), "text": battery.get("action_taken")} if battery else None,
        },
        "history": events[:HISTORY_ROWS],
        "can": {
            "self_test": bool(ups.get("available")) and over_nut,
            "practice": bool(ups.get("available")),
            "sockets": path.get("by") == "kiboto" and over_nut,
        },
        "ups": {"model": ups.get("model"), "mode": mode, "protocol": ups.get("protocol")},
    }
