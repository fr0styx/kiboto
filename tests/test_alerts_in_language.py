"""Activity finding: every alert Kiboto sends reads in the household's language (NUX-3). Some were
English only (cloud and two-way sync, drive checks, copies, off-site backup, ...)."""

import json
import os
import re

from backend import i18n
from backend.services import notifications

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# calls that pass their text through a dict built elsewhere (alert_rules' callers, _backup_notice)
THROUGH_A_DICT = {"backend/services/alert_rules.py", "backend/services/backup_engine.py"}


def _calls_without_text():
    found = []
    for base, _dirs, files in os.walk(os.path.join(ROOT, "backend")):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            rel = os.path.relpath(path, ROOT)
            if rel in THROUGH_A_DICT:
                continue
            with open(path, encoding="utf-8") as f:
                src = f.read()
            for m in re.finditer(r"(?<!def )send_notification\(", src):
                i, depth = m.end(), 1
                while depth and i < len(src):
                    depth += {"(": 1, ")": -1}.get(src[i], 0)
                    i += 1
                if "text" not in src[m.start() : i]:
                    found.append(f"{rel}:{src[: m.start()].count(chr(10)) + 1}")
    return found


def test_every_alert_carries_its_text_keys():
    assert _calls_without_text() == []


def test_the_server_can_say_activity_texts_in_the_household_language():
    with open(os.path.join(ROOT, "backend", "locales", "de.json"), encoding="utf-8") as f:
        de = json.load(f)
    assert "ev.copy_done.title" in de and "alert.cloud_sync_failed.msg" in de


def test_an_event_text_is_translated_for_an_alert(monkeypatch):
    from backend.state import event_text

    monkeypatch.setattr(notifications, "alert_language", lambda: "de")
    title, msg = notifications.in_household_language("Copy finished", "3 files copied.", event_text("copy_done", n=3))
    assert title == i18n.text("ev.copy_done.title", "", {}, "de") and title != "Copy finished"
    assert "3" in msg


def test_new_alert_texts(monkeypatch):
    monkeypatch.setattr(notifications, "alert_language", lambda: "fr")
    title, msg = notifications.in_household_language(
        "Cloud Sync Failed",
        "x",
        notifications.alert_text("cloud_sync_failed", action="copy", src="a", dst="b", error="boom"),
    )
    assert title == "La copie dans le cloud a échoué" and msg == "a → b : boom"


def test_two_way_sync_and_replication_alerts_carry_keys(monkeypatch):
    sent = []
    monkeypatch.setattr(notifications, "send_notification", lambda *a, **k: sent.append((a, k)))
    from backend.services import replication_engine, two_way_sync

    two_way_sync._notify({"name": "Photos"}, "the other side is offline")
    replication_engine._notify("Replication failed: home", "disk full", "warning", "job1", "home")
    assert sent[0][0][0]["text"]["title_key"] == "alert.sync_stopped.title"
    assert sent[1][1]["text"] == notifications.alert_text("replication_failed", name="home", error="disk full")
