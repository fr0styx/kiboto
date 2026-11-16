"""SET-22 Storage 3: the bay picture's drives carry Drive Health's stored verdict, from memory."""

import time

from backend.api import chassis
from backend.state import Z_STATE


def test_a_drive_carries_its_stored_verdict_in_drive_healths_words(monkeypatch):
    now = time.time()
    verdicts = {
        "sda": {"verdict": "soon", "kind": "replace", "ts": now},
        "sdb": {"verdict": "ok", "kind": "", "ts": now},
        "sdc": {"verdict": "now", "kind": "other", "ts": now - 10 * 86400},  # too old: no word
        "nvme0n1": {"verdict": "watch", "ts": now},
    }
    monkeypatch.setattr(Z_STATE.smart, "snapshot", lambda name: verdicts if name == "verdicts" else {})
    status = {
        "bays": [{"disk": {"dev": "sda"}}, {"disk": {"dev": "sdb"}}, {"disk": {"dev": "sdc"}}, {"disk": None}],
        "nvme_slots": [{"disk": {"dev": "nvme0n1"}}, {"disk": None}],
    }
    out = chassis.with_verdicts(status)
    assert out["bays"][0]["disk"]["verdict_label_key"] == "soon_replace"
    assert out["bays"][1]["disk"]["verdict_label_key"] == "ok"
    assert "verdict" not in out["bays"][2]["disk"]
    assert out["nvme_slots"][0]["disk"]["verdict_label_key"] == "watch"


def test_no_verdict_or_an_unknown_one_adds_nothing():
    assert chassis.verdict_of("sdx", {}, time.time()) == {}
    assert chassis.verdict_of("sdx", {"sdx": {"verdict": "unknown", "ts": time.time()}}, time.time()) == {}
    assert chassis.verdict_of("sdx", {"sdx": {"verdict": "now", "kind": "other", "ts": time.time()}}, time.time()) == {
        "verdict": "now",
        "verdict_label_key": "now_other",
    }
