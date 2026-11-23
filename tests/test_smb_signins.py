"""Failed SMB sign-ins on a managed host count against the address and show in the sign-in history."""

import json

import pytest

from backend.services import ip_block, samba_host, smb_signins


def _line(status="NT_STATUS_WRONG_PASSWORD", remote="ipv4:192.0.2.7:51234", user="ana"):
    return json.dumps(
        {
            "timestamp": "2026-11-23T14:44:29.377588+0000",
            "type": "Authentication",
            "Authentication": {"status": status, "remoteAddress": remote, "clientAccount": user},
        }
    )


@pytest.fixture
def log(tmp_path, monkeypatch):
    smb_signins._reset_for_tests()
    ip_block._reset_for_tests()
    events = []
    monkeypatch.setattr("backend.users_db.log_security_event", lambda *a, **k: events.append((a, k)))
    monkeypatch.setattr(
        ip_block, "block", lambda ip, reason, seconds=None: events.append(("block", ip, reason)) or True
    )
    path = tmp_path / "auth.json"
    path.write_text(_line() + "\n")  # from before Kiboto started: not counted
    yield type("Log", (), {"path": str(path), "events": events})
    smb_signins._reset_for_tests()
    ip_block._reset_for_tests()


def _add(path, *lines, partial=""):
    with open(path, "a", encoding="utf-8") as f:
        f.write("".join(line + "\n" for line in lines) + partial)


def test_the_address_is_read_from_what_samba_writes():
    assert smb_signins.ip_of("ipv4:192.0.2.7:51234") == "192.0.2.7"
    assert smb_signins.ip_of("ipv6:2001:db8::1:445") == "2001:db8::1"
    assert smb_signins.ip_of("ipv6:[2001:db8::2]:445") == "2001:db8::2"
    assert smb_signins.ip_of("unix:/run/x") == "" and smb_signins.ip_of("") == ""


def test_new_failures_are_counted_once_and_old_ones_not_at_all(log):
    assert smb_signins.check_once(log.path) == 0  # the start: the end of the file is noted
    _add(
        log.path,
        _line(),
        _line(user="ben"),
        _line(status="NT_STATUS_OK"),
        "not json",
        _line(remote="unix:x"),
        partial=_line()[:40],
    )
    assert smb_signins.check_once(log.path) == 2
    history = [k for a, k in (e for e in log.events if len(e) == 2) if a and a[0] == "smb.login.failure"]
    assert sorted((h["actor_username"], h["details"]["count"]) for h in history) == [("ana", 1), ("ben", 1)]
    assert smb_signins.check_once(log.path) == 0  # nothing new; the half line waits
    _add(log.path, _line()[40:])
    assert smb_signins.check_once(log.path) == 1


def test_twenty_failures_block_the_address_and_say_so(log):
    smb_signins.check_once(log.path)
    _add(log.path, *[_line() for _ in range(20)])
    assert smb_signins.check_once(log.path) == 20
    assert ("block", "192.0.2.7", "20 failed SMB sign-ins in 15 minutes") in log.events
    logged = [e for e in log.events if len(e) == 2]
    assert any(a and a[0] == "auth.lockout" and k["details"] == {"service": "SMB"} for a, k in logged)
    one = [k for a, k in logged if a and a[0] == "smb.login.failure"]
    assert len(one) == 1 and one[0]["details"]["count"] == 20


def test_a_new_or_shorter_file_is_read_from_its_start_and_a_missing_one_is_quiet(log, tmp_path):
    smb_signins.check_once(log.path)
    (tmp_path / "auth.json").unlink()
    assert smb_signins.check_once(log.path) == 0
    (tmp_path / "auth.json").write_text(_line() + "\n")
    assert smb_signins.check_once(log.path) == 1


def test_the_loop_says_what_went_wrong_and_goes_on(monkeypatch):
    calls = []
    monkeypatch.setattr(smb_signins, "check_once", lambda: calls.append(1) or (_ for _ in ()).throw(OSError("x")))
    monkeypatch.setattr(smb_signins.time, "sleep", lambda s: None)
    smb_signins.keep_watching(rounds=2)
    assert len(calls) == 2


def test_the_file_server_writes_the_failures_where_they_are_read():
    lines = samba_host.global_lines("/var/lib/kiboto/samba")
    assert f"   log level = 0 auth_json_audit:2@{smb_signins.AUTH_LOG}" in lines
