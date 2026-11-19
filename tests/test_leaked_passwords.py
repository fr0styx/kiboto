"""The leaked-password check (owner, 19 Nov 2026): off by default, only five characters of a hash
leave the NAS, and a service that is down never blocks a password change."""

import hashlib

import httpx
import pytest

from backend import leaked_passwords, outside_checks, password_policy

PW = "correct horse battery staple 42"
DIGEST = hashlib.sha1(PW.encode(), usedforsecurity=False).hexdigest().upper()


@pytest.fixture(autouse=True)
def fresh_state(tmp_path, monkeypatch):
    monkeypatch.setattr(outside_checks, "STATE_FILE", str(tmp_path / "outside_checks.json"))


def _answer(count):
    return f"0018A45C4D1DEF81644B54AB7F969B88D65:1\r\n{DIGEST[5:]}:{count}\r\nFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF:0\r\n"


def test_only_the_first_five_characters_of_the_hash_are_sent():
    asked = []

    def fetch(prefix):
        asked.append(prefix)
        return _answer(3861493)

    assert leaked_passwords.times_leaked(PW, fetch) == 3861493
    assert asked == [DIGEST[:5]] and len(asked[0]) == 5 and PW not in asked[0]


def test_not_in_the_list_a_padded_line_and_a_count_that_is_no_number():
    assert leaked_passwords.times_leaked(PW, lambda p: "0018A45C4D1DEF81644B54AB7F969B88D65:12\r\n") == 0
    assert leaked_passwords.times_leaked(PW, lambda p: f"{DIGEST[5:]}:0\r\n") == 0  # padding has count 0
    assert leaked_passwords.times_leaked(PW, lambda p: f"{DIGEST[5:].lower()}:many\r\n") == 1


def test_a_service_that_is_down_accepts_the_password():
    def down(prefix):
        raise httpx.ConnectError("no route")

    assert leaked_passwords.times_leaked(PW, down) is None
    outside_checks.set_enabled("leaked_passwords", True)
    assert leaked_passwords.problem(PW, down) is None


def test_off_by_default_nothing_is_asked():
    def never(prefix):
        raise AssertionError("asked while the check is off")

    assert outside_checks.state()["leaked_passwords"] is False and not any(outside_checks.state().values())
    assert leaked_passwords.problem(PW, never) is None


def test_on_a_leaked_password_is_refused_with_the_count_and_a_clean_one_passes(monkeypatch):
    outside_checks.set_enabled("leaked_passwords", True)
    text = leaked_passwords.problem(PW, lambda p: _answer(3861493))
    assert "known data leaks (3,861,493 times)" in text
    assert leaked_passwords.problem(PW, lambda p: _answer(0)) is None
    # the password rule everyone goes through asks it too
    monkeypatch.setattr(leaked_passwords, "_fetch", lambda p: _answer(7))
    assert "known data leaks (7 times)" in password_policy.password_problem(PW)
    monkeypatch.setattr(leaked_passwords, "_fetch", lambda p: "")
    assert password_policy.password_problem(PW) is None
    assert "at least" in password_policy.password_problem("short")  # the local rules come first


def test_the_real_fetch_sends_padding_and_raises_on_an_error(monkeypatch):
    seen = {}

    class Res:
        text = "ABC:1"

        def raise_for_status(self):
            seen["checked"] = True

    def fake_get(url, headers=None, timeout=None):
        seen.update(url=url, headers=headers, timeout=timeout)
        return Res()

    monkeypatch.setattr(httpx, "get", fake_get)
    assert leaked_passwords._fetch("ABCDE") == "ABC:1"
    assert seen["url"] == "https://api.pwnedpasswords.com/range/ABCDE"
    assert seen["headers"]["Add-Padding"] == "true" and seen["checked"] and seen["timeout"] == leaked_passwords.TIMEOUT


def test_an_unknown_check_cannot_be_switched():
    with pytest.raises(KeyError):
        outside_checks.set_enabled("telemetry", True)
    assert outside_checks.enabled("telemetry") is False


def test_the_routes(client):
    assert client.get("/api/security/outside-checks").status_code in (401, 403)
    h = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'password': 'admin'}).json()['token']}"}
    checks = client.get("/api/security/outside-checks", headers=h).json()["checks"]
    assert checks[0] == {"name": "leaked_passwords", "enabled": False} and not any(c["enabled"] for c in checks)
    res = client.put("/api/security/outside-checks", headers=h, json={"name": "leaked_passwords", "enabled": True})
    assert res.status_code == 200 and res.json()["checks"][0]["enabled"] is True
    assert (
        client.put("/api/security/outside-checks", headers=h, json={"name": "nope", "enabled": True}).status_code == 400
    )
    logs = client.get("/api/auth/audit?limit=5", headers=h).json()["audit_logs"]
    assert any(r["event_type"] == "security.outside_check.changed" for r in logs)
