"""Why an update did not take, in the reader's language: each reason the updater records is a text key."""

import json
import re
from pathlib import Path

import pytest

from backend import i18n
from backend.services import self_updater as su

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "backend/services/self_updater.py").read_text(encoding="utf-8")


def _locale(lang):
    text = (ROOT / f"frontend/src/locales/{lang}.js").read_text(encoding="utf-8")
    return {m.group(1): json.loads(m.group(2)) for m in re.finditer(r'^  "([^"]+)": (".*"),$', text, re.M)}


@pytest.mark.parametrize(
    "reason,kind,params",
    [
        ("could not snapshot the data folder: disk full", "snapshot", {"error": "disk full"}),
        ("could not restore the earlier data: busy", "restore", {"error": "busy"}),
        ("could not keep the current version aside", "keep_aside", {}),
        ("the new version's container could not be created", "create", {}),
        ("could not connect network br0", "network", {"network": "br0"}),
        ("the new version did not start", "not_started", {}),
        ("container exited (code 137)", "exited", {"code": "137"}),
        ("healthcheck reported unhealthy", "unhealthy", {}),
        ("the app reported a failed part (degraded)", "degraded", {}),
        ("timed out waiting for the app to report ok", "timeout", {}),
    ],
)
def test_each_recorded_reason_has_its_words(reason, kind, params):
    words = su.reason_words(reason)
    assert words == {"key": f"ev.update_reason.{kind}", "default": reason, "params": params}
    # in English the words are the reason as recorded; every language names the same values
    en = _locale("en")
    assert i18n.fill(en[words["key"]], params) == reason
    for lang in ("de", "es", "fr", "zh"):
        assert set(re.findall(r"\{(\w+)\}", _locale(lang)[words["key"]])) == set(params), lang


def test_a_reason_it_does_not_know_stays_as_written():
    assert su.reason_words("something new") == "something new"
    assert su.reason_words("") == ""


def test_every_reason_the_updater_writes_is_known():
    written = re.findall(r'write_update_result\(\s*data_dir,\s*"(?:not_applied|rolled_back)",\s*f?"([^"]+)"', SRC)
    assert len(written) >= 6
    for text in written:
        sample = re.sub(r"\{[^}]+\}", "x", text)
        assert isinstance(su.reason_words(sample), dict), text
    for literal in re.findall(r'return False, f?"([^"]+)"', SRC):
        assert isinstance(su.reason_words(re.sub(r"\{[^}]+\}", "1", literal)), dict), literal


def test_the_activity_entry_carries_the_reason_in_words(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr("backend.state.add_event", lambda *a, **k: events.append(a))
    monkeypatch.setattr("backend.services.notifications.send_notification", lambda *a, **k: None)
    su.write_update_result(str(tmp_path), "rolled_back", "container exited (code 1)", to_image="img:2")
    su.report_last_update_result(str(tmp_path))
    details = events[0][3]
    assert details["msg_key"] == "ev.update_rolled_back.msg"
    assert details["params"]["reason"]["key"] == "ev.update_reason.exited"
    # the server's own copy (e-mail, push) fills it in the household's language
    assert "Code 1" in i18n.text(details["msg_key"], "", details["params"], "de")


def test_last_result_says_the_reason_in_words(client, auth_headers, tmp_path, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    su.write_update_result(str(tmp_path), "rolled_back", "the new version did not start", to_image="img:3")
    body = client.get("/api/system/updates/last-result", headers=auth_headers).json()
    assert body["reason"] == "the new version did not start"
    assert body["reason_text"]["key"] == "ev.update_reason.not_started"
    su.write_update_result(str(tmp_path), "updated", "ok for 60 s", to_image="img:4")
    body = client.get("/api/system/updates/last-result", headers=auth_headers).json()
    assert "reason_text" not in body or body["reason_text"] is None
