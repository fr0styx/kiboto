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
        for name in ("app_updated", "app_update_failed", "app_update_back", "app_update_stuck"):
            assert msgs.get(f"ev.{name}.title") and msgs.get(f"ev.{name}.msg"), (lang, name)
