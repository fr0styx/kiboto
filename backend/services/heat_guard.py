"""Switch off when too hot (hardware report, the optional extras; owner 18 Nov: build it, off by default).

A last line of defence for when the fans cannot keep up, say a fan failed or a vent is blocked. The
fans already run at full speed from 55 °C (NVMe 75 °C); this acts a step later. An awake hard drive at
60 °C, or an NVMe drive at 80 °C, warns at once. If one stays that hot for three minutes, Kiboto stops
the virtual machines and the apps, saves what is in memory and switches the NAS off. Where Kiboto has no
way to switch the host off (Kiboto in a container on Unraid), it stops what it can and asks for the NAS
to be switched off by hand. Sleeping drives are never woken or counted. Nothing here touches the fans.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json
from backend.ignored_errors import ignored

# what a step can raise: files and commands (OSError, TimeoutError), a refused or odd answer
_STEP_ERRORS = (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError)

SETTINGS_FILE = os.path.join(DATA_DIR, "heat_shutdown.json")
HDD_LIMIT_C = 60
NVME_LIMIT_C = 80
HOLD_SECS = 180
REARM_MARGIN_C = 5

_lock = threading.Lock()
_state: dict[str, Any] = {"since": {}, "warned": False, "engaged": False}


def enabled() -> bool:
    return bool((read_json(SETTINGS_FILE, {}) or {}).get("enabled", False))


def _last() -> dict[str, Any] | None:
    return (read_json(SETTINGS_FILE, {}) or {}).get("last")


@json_locked(lambda *a, **k: SETTINGS_FILE)
def _save(**changes: Any) -> None:
    data = dict(read_json(SETTINGS_FILE, {}) or {})
    data.update(changes)
    atomic_write_json(SETTINGS_FILE, data)


def can_power_off() -> bool:
    from backend.services import host_power

    return bool(host_power.can("shutdown").get("ok"))


def public_state() -> dict[str, Any]:
    return {
        "enabled": enabled(),
        "hdd_c": HDD_LIMIT_C,
        "nvme_c": NVME_LIMIT_C,
        "hold_min": HOLD_SECS // 60,
        "can_power_off": can_power_off(),
        "engaged": _state["engaged"],
        "last": _last(),
    }


def set_enabled(on: bool) -> dict[str, Any]:
    _save(enabled=bool(on))
    if not on:
        with _lock:
            _state.update(since={}, warned=False)
    return public_state()


def _is_nvme(d: dict[str, Any]) -> bool:
    return bool(d.get("is_nvme") or str(d.get("dev", "")).startswith("nvme") or str(d.get("name", "")).startswith("nv"))


def _readings(disks: list[dict[str, Any]] | None) -> list[tuple[str, int, int]]:
    """(name, temperature, limit) of every awake drive with a reading."""
    out = []
    for d in disks or []:
        temp = d.get("temp")
        if temp is None or d.get("standby"):
            continue
        name = str(d.get("name") or d.get("dev") or "?")
        out.append((name, round(float(temp)), NVME_LIMIT_C if _is_nvme(d) else HDD_LIMIT_C))
    return out


def _words(hot: list[tuple[str, int, int]]) -> str:
    return ", ".join(f"{name} {temp} °C" for name, temp, _ in hot)


def check(disks: list[dict[str, Any]] | None, now: float | None = None, start=None) -> str | None:
    """Called once per stats round. "warned" when a drive first reaches its limit, "engaged" when one
    stayed there for HOLD_SECS (the switch-off then runs on its own thread), else None."""
    if not enabled():
        with _lock:
            _state.update(since={}, warned=False)
        return None
    now = time.time() if now is None else now
    readings = _readings(disks)
    hot = [r for r in readings if r[1] >= r[2]]
    with _lock:
        if _state["engaged"]:
            # armed again once every awake drive is well under its limit
            if all(temp < limit - REARM_MARGIN_C for _, temp, limit in readings):
                _state.update(engaged=False, since={}, warned=False)
            return None
        names = {name for name, _, _ in hot}
        since = {n: t for n, t in _state["since"].items() if n in names}
        for name in names:
            since.setdefault(name, now)
        _state["since"] = since
        if not hot:
            _state["warned"] = False
            return None
        if not _state["warned"]:
            _state["warned"] = True
            first = True
        else:
            first = False
            if now - min(since.values()) >= HOLD_SECS:
                _state["engaged"] = True
                (start or _start_thread)(hot)
                return "engaged"
    if first:
        _warn(hot)
        return "warned"
    return None


def _start_thread(hot: list[tuple[str, int, int]]) -> None:
    threading.Thread(target=switch_off, args=(hot,), name="HeatGuard", daemon=True).start()


def _notify(title: str, message: str, level: str, alert: str, **params: Any) -> None:
    try:
        from backend.services.notifications import alert_text, send_notification

        send_notification(
            title=title, message=message, level=level, event_type="temp", text=alert_text(alert, **params)
        )
    except _STEP_ERRORS:
        ignored("heat_guard.notify")


def _warn(hot: list[tuple[str, int, int]]) -> None:
    words = _words(hot)
    minutes = HOLD_SECS // 60
    if can_power_off():
        _notify(
            "Too hot: the NAS may switch off",
            f"{words}. If it stays this hot for {minutes} minutes, Kiboto stops the apps and switches the NAS off.",
            "critical",
            "heat_warn",
            drives=words,
            minutes=minutes,
        )
    else:
        _notify(
            "Too hot: the apps may be stopped",
            f"{words}. If it stays this hot for {minutes} minutes, Kiboto stops the apps and virtual machines.",
            "critical",
            "heat_warn_apps",
            drives=words,
            minutes=minutes,
        )


def _step(name: str, fn, *args: Any) -> Any:
    try:
        return fn(*args)
    except _STEP_ERRORS:
        ignored(f"heat_guard.{name}")  # logged; the next step runs
        return None


def _machines() -> None:
    from backend.services import vm_qemu

    vm_qemu.machines_first(False)


def _apps() -> None:
    from backend.services.ups_watchdog import graceful_docker_teardown

    graceful_docker_teardown(30)


def switch_off(hot: list[tuple[str, int, int]]) -> str:
    """Stops the virtual machines and the apps, saves what is in memory, then switches the NAS off;
    "off", "failed" or "by_hand" (no way to switch this host off)."""
    from backend.state import add_event, event_text

    words = _words(hot)
    logger.critical("[HeatGuard] Too hot for %d minutes: %s. Switching off.", HOLD_SECS // 60, words)
    add_event(
        "critical",
        "Too hot: switching off",
        f"{words} for {HOLD_SECS // 60} minutes. Stopping the virtual machines and apps.",
        event_text("heat_shutdown", drives=words, minutes=HOLD_SECS // 60),
    )
    able = _step("ask whether the NAS can be switched off", can_power_off)
    _step("stop the virtual machines", _machines)
    _step("stop the apps", _apps)
    _step("save what is in memory", os.sync)
    outcome = "by_hand"
    if able:
        from backend.services import host_power

        started = _step("switch the NAS off", lambda: host_power.run("shutdown")["started"])
        outcome = "off" if started else "failed"
    if outcome != "off":
        _notify(
            "Too hot: switch the NAS off by hand",
            f"{words}. Kiboto stopped the apps and virtual machines but cannot switch this NAS off itself. "
            "Switch it off by hand and check the fans and the air around it.",
            "critical",
            "heat_manual",
            drives=words,
        )
    _save(last={"at": time.time(), "outcome": outcome, "drives": words})
    return outcome
