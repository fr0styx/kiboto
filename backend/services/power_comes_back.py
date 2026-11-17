"""Whether the NAS switched on again by itself after a power cut (SET-31, Power stage 5; Power
decision 6): the safe shutdown notes the cut, the next start turns the note into one question, and
the owner's answer is kept. Its own module, so the UPS watchdog and the Power summary can both use
it without importing each other."""

from __future__ import annotations

import os
import time
from typing import Any

from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, read_json

COMES_BACK_FILE = os.path.join(DATA_DIR, "power_comes_back.json")


def record() -> dict[str, Any]:
    rec = read_json(COMES_BACK_FILE, {}) or {}
    return rec if isinstance(rec, dict) else {}


def remember_power_cut(now: float | None = None) -> None:
    """The safe shutdown for a power cut is under way (written before the disks are flushed)."""
    atomic_write_json(COMES_BACK_FILE, {**record(), "cut_at": now if now is not None else time.time()})


def forget_power_cut() -> None:
    """The NAS was not switched off after all (no host command): nothing to ask about."""
    rec = record()
    if rec.pop("cut_at", None) is not None:
        atomic_write_json(COMES_BACK_FILE, rec)


def ask_after_start() -> bool:
    """At start: when the last stop was Kiboto's safe shutdown for a power cut, Power asks once
    whether the NAS switched on again by itself (Power decision 6: proven only by a real one)."""
    rec = record()
    cut = rec.pop("cut_at", None)
    if cut is None:
        return False
    rec["ask_at"] = cut
    atomic_write_json(COMES_BACK_FILE, rec)
    return True


def answer(by_itself: bool) -> None:
    """Keeps the answer to the one question: proven on the date of the cut, or not; asks no more."""
    rec = record()
    at = rec.pop("ask_at", None)
    if at is None:
        raise ValueError("There is no power cut to answer about.")
    rec.pop("failed_at" if by_itself else "proven_at", None)
    rec["proven_at" if by_itself else "failed_at"] = at
    atomic_write_json(COMES_BACK_FILE, rec)
