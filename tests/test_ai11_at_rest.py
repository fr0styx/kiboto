"""AI decision 11: Kib's Privacy section says whether chats and the index are encrypted on this NAS."""

import pytest

from backend import db_crypto
from backend.api import media


@pytest.mark.parametrize(
    "states,key,word",
    [
        (("encrypted", "encrypted"), True, "encrypted"),
        (("encrypted", "encrypting"), True, "encrypting"),
        (("plain", "encrypted"), True, "encrypting"),  # waiting for conversion
        (("locked", "encrypted"), True, "locked"),
        (("off", "off"), False, "off"),
        (("encrypted", "off"), False, "off"),  # only one of the two: not "encrypted"
    ],
)
def test_one_word_for_both_files(monkeypatch, states, key, word):
    it = iter(states)
    monkeypatch.setattr(db_crypto, "status", lambda path: next(it))
    monkeypatch.setattr(db_crypto, "enabled", lambda: key)
    assert media.encryption_at_rest() == word


def test_the_settings_read_carries_it(client, auth_headers, monkeypatch):
    monkeypatch.setattr(media, "encryption_at_rest", lambda: "off")
    body = client.get("/api/ai/config", headers=auth_headers).json()
    assert body["at_rest"] == "off" and "enabled" in body
