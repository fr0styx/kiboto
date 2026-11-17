"""Jobs carry their error's message key and values, so the Jobs centre shows it in the reader's
language; the English stays for logs. Every app-update event has its texts in each language."""

import json
import os

from backend.services.jobs import job_manager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_finish_keeps_the_error_key_and_values():
    job = job_manager.register("app_update", "Update shop", title_id="jobs.t.app_update", title_params={"name": "shop"})
    job_manager.finish(
        job.id,
        "error",
        "web could not be updated: x.",
        error_id="jobs.e.app_update_failed",
        error_params={"name": "web", "reason": "x"},
    )
    row = next(j for j in job_manager.list(everyone=True)["history"] if j["id"] == job.id)
    assert row["error_id"] == "jobs.e.app_update_failed" and row["error_params"] == {"name": "web", "reason": "x"}
    other = job_manager.register("app_update", "Update b")
    job_manager.finish(other.id, "done")
    row = next(j for j in job_manager.list(everyone=True)["history"] if j["id"] == other.id)
    assert row["error_id"] == "" and row["error_params"] == {}


def test_every_app_update_event_has_its_texts_in_each_language():
    for lang in ("en", "de", "es", "fr", "zh"):
        with open(os.path.join(ROOT, "backend", "locales", f"{lang}.json"), encoding="utf-8") as fh:
            msgs = json.load(fh)
        for name in (
            "app_updated",
            "app_update_failed",
            "app_update_back",
            "app_update_stuck",
            "power_night_off",
            "power_night_no_clock",
            "stack_applied",
            "stack_not_applied",
            "files_received",
        ):
            assert msgs.get(f"ev.{name}.title") and msgs.get(f"ev.{name}.msg"), (lang, name)


def test_the_night_switch_off_tells_the_log_in_the_reader_s_language(monkeypatch):
    from backend import state
    from backend.services import power_schedule

    seen = []
    monkeypatch.setattr(state, "add_event", lambda *a, **k: seen.append(a))
    power_schedule._tell("off", wake_at="06:30")
    power_schedule._tell("no_wake")
    assert seen[0][3] == {
        "title_key": "ev.power_night_off.title",
        "msg_key": "ev.power_night_off.msg",
        "params": {"wake": "06:30"},
    }
    assert seen[1][3]["msg_key"] == "ev.power_night_no_clock.msg"
