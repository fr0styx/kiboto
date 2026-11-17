"""The Security Advisor's one-click fixes say what they did in the reader's language."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.errors import SaidText
from backend.services import safe_defaults_advisor as sda

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(sda.__file__).read_text(encoding="utf-8")


def _locale(lang):
    text = (ROOT / f"frontend/src/locales/{lang}.js").read_text(encoding="utf-8")
    return {m.group(1): json.loads(m.group(2)) for m in re.finditer(r'^  "([^"]+)": (".*"),$', text, re.M)}


EN = _locale("en")


def check(message):
    """A fix's answer is a sentence that says how it was made, and reads the same in English."""
    assert isinstance(message, SaidText)
    template = EN[message.text["msg_key"]]
    params = message.text["params"]
    assert set(re.findall(r"\{(\w+)\}", template)) <= set(params)
    for name, value in params.items():
        template = template.replace("{" + name + "}", str(value))
    assert template == str(message)


def test_every_fix_sentence_is_known_in_every_language():
    keys = set(re.findall(r'"(sec_fixed_[a-z_]+)"', SRC))
    assert len(keys) >= 9
    for lang in ("de", "es", "fr", "zh"):
        strings = _locale(lang)
        for key in keys:
            en = EN[f"srv.{key}"]
            assert set(re.findall(r"\{(\w+)\}", strings[f"srv.{key}"])) == set(re.findall(r"\{(\w+)\}", en)), (
                lang,
                key,
            )
    for sentence, key in re.findall(r'SaidText\("([^"{]+)", "([a-z_]+)"\)', SRC):
        assert EN[f"srv.{key}"] == sentence


class Share:
    def __init__(self, name, guest_ok=True):
        self.name, self.guest_ok = name, guest_ok

    def model_copy(self, update):
        return Share(self.name, update.get("guest_ok", self.guest_ok))


@pytest.mark.parametrize(
    "shares,broken,key",
    [
        ([Share("open")], set(), "srv.sec_fixed_smb"),
        ([Share("open"), Share("kids")], {"kids"}, "srv.sec_fixed_smb_partly"),
        ([Share("kids")], {"kids"}, "srv.sec_fixed_smb_failed"),
        ([Share("p", guest_ok=False)], set(), "srv.sec_fixed_nothing_changed"),
    ],
)
def test_the_samba_fix_says_each_outcome(monkeypatch, shares, broken, key):
    def save(share):
        if share.name in broken:
            raise OSError("busy")
        return share

    engine = SimpleNamespace(list_shares=lambda: shares, add_or_update_share=save)
    monkeypatch.setattr("backend.services.samba_engine.get_samba_engine", lambda: engine)
    message = sda._fix_smb_guest()
    assert message.text["msg_key"] == key
    check(message)


def test_nfs_and_snapshots_with_nothing_to_do(monkeypatch):
    monkeypatch.setattr(sda, "_open_nfs_exports", lambda: [])
    monkeypatch.setattr("backend.services.nfs_engine.get_nfs_engine", lambda: None)
    monkeypatch.setattr("backend.services.nfs_engine.home_network", lambda: "192.168.1.0/24")
    check(sda._fix_nfs_open_exports())
    monkeypatch.setattr(sda, "_shares_without_snapshots", lambda: [])
    message = sda._fix_snapshots_off()
    assert message.text["msg_key"] == "srv.sec_fixed_nothing"
    check(message)


def test_the_answer_and_the_activity_entry_say_how(client, auth_headers, monkeypatch):
    events = []
    monkeypatch.setitem(
        sda.FIXES, "ai_search_family", lambda: SaidText("AI search is off for kids and guests.", "sec_fixed_ai")
    )
    monkeypatch.setattr("backend.state.add_event", lambda *a, **k: events.append((a, k)))
    res = client.post("/api/system/security-posture/fix/ai_search_family", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["message"] == "AI search is off for kids and guests."
    assert body["text"] == {"msg_key": "srv.sec_fixed_ai", "params": {}}
    details = events[0][1]["details"]
    assert details["msg_key"] == "ev.security_fix_applied.msg" and details["fix"] == "ai_search_family"
    assert details["params"]["change"]["key"] == "srv.sec_fixed_ai"


def test_a_fix_that_answers_plain_words_still_works(client, auth_headers, monkeypatch):
    monkeypatch.setitem(sda.FIXES, "ai_search_family", lambda: "Done.")
    monkeypatch.setattr("backend.state.add_event", lambda *a, **k: None)
    body = client.post("/api/system/security-posture/fix/ai_search_family", headers=auth_headers).json()
    assert body["message"] == "Done." and body["text"] is None
