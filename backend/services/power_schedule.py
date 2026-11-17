"""Scheduled power (audit A10, owner decision 16 Nov 2026: build it, off by default; the owner tests
one night on the real machine). At the chosen time the NAS sets its wake-up clock (the RTC alarm),
checks that the alarm took, lets virtual machines shut down, and switches off; the RTC wakes it at
the chosen morning time. It never switches off without a wake-up set, and a busy NAS (a job or a
virtual machine still running) waits up to two hours."""

from __future__ import annotations

import datetime as dt
import os
import re
import time
from collections.abc import Callable
from typing import Any

from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, read_json

STATE_FILE = os.path.join(DATA_DIR, "power_schedule.json")
RTC_PATHS = ("/host/sys/class/rtc/rtc0/wakealarm", "/sys/class/rtc/rtc0/wakealarm")
WAIT_STEP_MIN = 30
WAIT_MAX_MIN = 120
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _defaults() -> dict[str, Any]:
    return {
        "enabled": False,
        "off_at": "01:00",
        "wake_at": "07:00",
        "days": [0, 1, 2, 3, 4, 5, 6],
        "last_off": "",
        "postponed_min": 0,
        "last_note": "",
    }


def state() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    return {**_defaults(), **(data if isinstance(data, dict) else {})}


def rtc_path() -> str:
    return next((p for p in RTC_PATHS if os.path.exists(p) and os.access(p, os.W_OK)), "")


def public_state() -> dict[str, Any]:
    st = state()
    st["wake_possible"] = bool(rtc_path())
    return st


def save(enabled: bool, off_at: str, wake_at: str, days: list[int]) -> dict[str, Any]:
    if not (HHMM.match(off_at or "") and HHMM.match(wake_at or "")):
        raise ValueError("Use times like 01:00 and 07:00.")
    if off_at == wake_at:
        raise ValueError("The switch-off and wake-up times must differ.")
    days = sorted({int(d) for d in days if 0 <= int(d) <= 6})
    if enabled and not days:
        raise ValueError("Choose at least one night.")
    if enabled and not rtc_path():
        raise ValueError("This NAS's wake-up clock can't be set from Kiboto, so it would not come back on by itself.")
    st = state()
    st.update({"enabled": bool(enabled), "off_at": off_at, "wake_at": wake_at, "days": days, "postponed_min": 0})
    atomic_write_json(STATE_FILE, st)
    return public_state()


def next_wake(now: dt.datetime, wake_at: str) -> dt.datetime:
    h, m = (int(x) for x in wake_at.split(":"))
    w = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return w if w > now + dt.timedelta(minutes=10) else w + dt.timedelta(days=1)


def set_wake(when: dt.datetime, path: str) -> bool:
    """Writes the RTC alarm (cleared first, as the kernel asks) and reads it back."""
    epoch = int(when.timestamp())
    with open(path, "w", encoding="ascii") as f:
        f.write("0")
    with open(path, "w", encoding="ascii") as f:
        f.write(str(epoch))
    with open(path, encoding="ascii") as f:
        got = f.read().strip()
    return got.isdigit() and abs(int(got) - epoch) <= 2


def _busy() -> str:
    """Why the NAS shouldn't switch off now, or ""."""
    from backend.services import vm_qemu
    from backend.services.jobs import job_manager

    active = job_manager.list(everyone=True).get("active") or []
    if any(j.get("status") in ("running", "queued") for j in active):
        return "job"
    if any(v.get("state") == "running" and not v.get("autostart") for v in vm_qemu._load_vms()):
        return "vm"
    return ""


def tick(
    now: dt.datetime | None = None,
    *,
    busy: Callable[[], str] = _busy,
    rtc: Callable[[], str] = rtc_path,
    wake: Callable[[dt.datetime, str], bool] = set_wake,
    power_off: Callable[[], bool] | None = None,
) -> str:
    """Called every minute. Returns what it did: "", "postponed", "no_wake", "off" or "failed"."""
    st = state()
    now = now or dt.datetime.now()
    if not st["enabled"]:
        return ""
    h, m = (int(x) for x in st["off_at"].split(":"))
    due = now.replace(hour=h, minute=m, second=0, microsecond=0) + dt.timedelta(
        minutes=int(st.get("postponed_min") or 0)
    )
    night = (now - dt.timedelta(hours=12)).date().isoformat() if now.hour < 12 else now.date().isoformat()
    if st.get("last_off") == night or now < due or now > due + dt.timedelta(minutes=5):
        return ""
    if (now.weekday() if now.hour >= 12 else (now - dt.timedelta(days=1)).weekday()) not in st["days"]:
        return ""
    why = busy()
    if why and int(st.get("postponed_min") or 0) < WAIT_MAX_MIN:
        st["postponed_min"] = int(st.get("postponed_min") or 0) + WAIT_STEP_MIN
        st["last_note"] = f"postponed:{why}"
        atomic_write_json(STATE_FILE, st)
        return "postponed"
    st["postponed_min"] = 0
    st["last_off"] = night
    path = rtc()
    try:
        ok = bool(path) and wake(next_wake(now, st["wake_at"]), path)
    except OSError:
        ok = False
    if not ok:
        st["last_note"] = "no_wake"
        atomic_write_json(STATE_FILE, st)
        _tell("no_wake")
        return "no_wake"
    st["last_note"] = "off"
    atomic_write_json(STATE_FILE, st)
    _tell("off", wake_at=st["wake_at"])
    if power_off is None:  # the API layer passes the host shutdown in (services may not import it)
        st["last_note"] = "failed"
        atomic_write_json(STATE_FILE, st)
        return "failed"
    if not power_off():
        st["last_note"] = "failed"
        atomic_write_json(STATE_FILE, st)
        return "failed"
    return "off"


def _tell(what: str, **params: Any) -> None:
    from backend.state import add_event, event_text

    if what == "off":
        wake = str(params.get("wake_at"))
        add_event(
            "info",
            "Power schedule",
            f"Switching off for the night; waking at {wake}.",
            event_text("power_night_off", wake=wake),
        )
    else:
        add_event(
            "warning",
            "Power schedule",
            "Not switched off: the wake-up clock could not be set.",
            event_text("power_night_no_clock"),
        )


def loop_once(power_off: Callable[[], bool] | None = None) -> str:
    try:
        return tick(power_off=power_off)
    except (OSError, ValueError, RuntimeError):
        return "failed"


def sleep_seconds() -> float:
    return 60 - (time.time() % 60) + 1
