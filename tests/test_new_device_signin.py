"""Re-audit R1: a sign-in from a kind of device the account has not used before is recorded,
sent to the administrators and pushed to the person; a known device and the first one are quiet."""

import secrets
import sqlite3
import time

import pytest

from backend import users_db
from backend.services import known_devices, security_alerts

CHROME_WIN = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
SAFARI_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.0 Mobile/15E148 Safari/604.1"
EDGE_WIN = CHROME_WIN + " Edg/141.0.0.0"
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0"


@pytest.mark.parametrize(
    "ua, name",
    [
        (CHROME_WIN, "Chrome on Windows"),
        (SAFARI_IPHONE, "Safari on iPhone"),
        (EDGE_WIN, "Edge on Windows"),
        (FIREFOX_LINUX, "Firefox on Linux"),
        ("curl/8.5.0", "curl"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "Mac"),
        ("", ""),
    ],
)
def test_a_device_is_named_by_browser_and_system(ua, name):
    assert known_devices.describe(ua) == name


def test_an_internet_address_is_outside_home():
    assert known_devices.outside_home("8.8.8.8") is True
    for home in ("192.168.1.20", "10.0.0.5", "100.64.3.2", "127.0.0.1", "fe80::1%eth0", "", "not an address"):
        assert known_devices.outside_home(home) is False


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "users.db")
    users_db.init_users_db(path)
    uid = users_db.create_user("mara", "Mara", "P@ssword123!", role_id="share_user", db_path=path)["id"]
    return path, uid


def test_the_first_device_and_a_known_one_are_quiet_a_new_kind_is_not(db):
    path, uid = db
    assert known_devices.note_signin(uid, "192.168.1.20", CHROME_WIN, db_path=path) is None  # the first
    assert known_devices.note_signin(uid, "192.168.1.21", CHROME_WIN, db_path=path) is None  # known
    new = known_devices.note_signin(uid, "8.8.8.8", SAFARI_IPHONE, db_path=path)
    assert new == {"device": "Safari on iPhone", "outside": True}
    assert known_devices.note_signin(uid, "8.8.8.8", SAFARI_IPHONE, db_path=path) is None  # told once


def test_devices_signed_in_before_the_update_count_as_known(db):
    path, uid = db
    users_db.create_user_session(uid, "mara", ip="192.168.1.20", user_agent=CHROME_WIN, db_path=path)
    users_db.create_user_session(uid, "mara", ip="192.168.1.30", user_agent=SAFARI_IPHONE, db_path=path)
    assert known_devices.note_signin(uid, "192.168.1.20", CHROME_WIN, db_path=path) is None
    assert known_devices.note_signin(uid, "192.168.1.30", SAFARI_IPHONE, db_path=path) is None
    assert known_devices.note_signin(uid, "192.168.1.40", FIREFOX_LINUX, db_path=path)["device"] == "Firefox on Linux"


def test_a_new_device_sign_in_is_logged_pushed_and_alerted(client, monkeypatch):
    pushed, alerted = [], []
    monkeypatch.setattr(known_devices, "tell_person", lambda user, device, ip: pushed.append((user, device)))
    real = security_alerts.maybe_alert
    monkeypatch.setattr(
        security_alerts, "maybe_alert", lambda event, *a, **k: alerted.append(event) or real(event, *a, **k)
    )
    # the suite's admin has signed in before, from other tests: make sure it has a known device, then
    # sign in from a program no other test uses
    first = client.post("/api/auth/login", json={"password": "admin"}, headers={"User-Agent": CHROME_WIN})
    assert first.status_code == 200, first.text
    pushed.clear()
    alerted.clear()
    program = f"kibotest{secrets.token_hex(6)}"
    second = client.post("/api/auth/login", json={"password": "admin"}, headers={"User-Agent": f"{program}/1.0"})
    assert second.status_code == 200, second.text
    assert [d for _, d in pushed] == [program]
    assert "auth.login.new_device" in alerted
    logs = client.get("/api/auth/audit?limit=20", headers={"Authorization": f"Bearer {second.json()['token']}"}).json()
    row = next(r for r in logs["audit_logs"] if r["event_type"] == "auth.login.new_device")
    assert row["details"]["device"] == program and row["details"]["outside"] is False
    again = client.post("/api/auth/login", json={"password": "admin"}, headers={"User-Agent": f"{program}/1.0"})
    assert again.status_code == 200 and len(pushed) == 1


def test_the_alert_names_the_device():
    assert "auth.login.new_device" in security_alerts.ALERT_EVENTS
    text = security_alerts._describe("auth.login.new_device", "mara", "8.8.8.8", {"device": "Safari on iPhone"})
    assert "mara" in text and "Safari on iPhone" in text


def test_a_failure_to_remember_never_breaks_the_sign_in(monkeypatch):
    def boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(known_devices, "note_signin", boom)
    assert known_devices.signed_in({"id": "u1", "username": "mara"}, "192.168.1.2", CHROME_WIN, "password") is False


def test_the_person_is_told_in_the_household_language(monkeypatch):
    sent = []
    from backend.services import notifications, web_push

    monkeypatch.setattr(notifications, "alert_language", lambda: "de")
    monkeypatch.setattr(web_push, "notify", lambda title, body, **k: sent.append((title, body, k)) or {})
    known_devices.tell_person("mara", "Safari on iPhone", "8.8.8.8")
    deadline = time.time() + 5
    while not sent and time.time() < deadline:
        time.sleep(0.02)
    title, body, kw = sent[0]
    assert title == "Neue Anmeldung bei Ihrem Konto"
    assert "Safari on iPhone" in body and "8.8.8.8" in body and kw["users"] == ["mara"]
