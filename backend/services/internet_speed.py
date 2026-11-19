"""How fast is the internet line? (owner, 19 Nov 2026; off until turned on.)

The speed test on the Network page measures the link between a device and the NAS and asks
nothing outside. This one measures the home's line itself: the NAS fetches test bytes from
Cloudflare's public speed test and sends some back. Cloudflare sees the home's internet address
and nothing else. It only ever runs when someone presses the button, and only after an
administrator has turned the check on (backend/outside_checks.py).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import httpx

from backend import outside_checks
from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, read_json

HOST = "https://speed.cloudflare.com"
DOWN_BYTES = 100_000_000  # asked for; the reading stops at LIMIT_SECONDS
UP_BYTES = 10_000_000
LIMIT_SECONDS = 8.0
RESULT_FILE = os.path.join(DATA_DIR, "internet_speed.json")
_running = threading.Lock()


class TurnedOff(RuntimeError):
    """The check is off: nothing outside may be asked."""


class Busy(RuntimeError):
    """A measurement is already running."""


def _mbit(count: int, seconds: float) -> float:
    return round(count * 8 / 1_000_000 / max(seconds, 0.001), 1)


def _answer_time(client: httpx.Client, clock=time.perf_counter) -> float:
    times = []
    for _ in range(3):
        started = clock()
        client.get(f"{HOST}/__down", params={"bytes": 0}).raise_for_status()
        times.append((clock() - started) * 1000)
    return round(sorted(times)[1], 1)


def _download(client: httpx.Client, clock=time.perf_counter, limit: float = LIMIT_SECONDS) -> float:
    started = clock()
    received = 0
    with client.stream("GET", f"{HOST}/__down", params={"bytes": DOWN_BYTES}) as res:
        res.raise_for_status()
        for chunk in res.iter_bytes(256 * 1024):
            received += len(chunk)
            if clock() - started >= limit:
                break
    return _mbit(received, clock() - started)


def _upload(client: httpx.Client, clock=time.perf_counter) -> float:
    body = os.urandom(1_000_000) * (UP_BYTES // 1_000_000)
    started = clock()
    client.post(f"{HOST}/__up", content=body).raise_for_status()
    return _mbit(len(body), clock() - started)


def last() -> dict[str, Any] | None:
    data = read_json(RESULT_FILE, None)
    return data if isinstance(data, dict) else None


def view() -> dict[str, Any]:
    return {"enabled": outside_checks.enabled("internet_speed"), "last": last()}


def measure(client: httpx.Client | None = None, now=time.time) -> dict[str, Any]:
    """Measures the line and keeps the result. Raises TurnedOff, Busy, or httpx.HTTPError."""
    if not outside_checks.enabled("internet_speed"):
        raise TurnedOff("The internet speed test is turned off.")
    if not _running.acquire(blocking=False):
        raise Busy("A speed test is already running.")
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=6.0), headers={"User-Agent": "Kiboto"})
    try:
        result = {
            "answer_ms": _answer_time(client),
            "down_mbit": _download(client),
            "up_mbit": _upload(client),
            "measured_at": int(now()),
        }
        atomic_write_json(RESULT_FILE, result)
        return result
    finally:
        if own:
            client.close()
        _running.release()
