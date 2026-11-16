"""SET-14 / SET-23: the Overview and the security check agree. The Overview counts exactly the rows
the check calls "Needs a look" (failed, and they count); the first-time password has its own row."""

from backend.services import security_advisor, status_summary


def _posture(*rows):
    checks = [{"id": i, "passed": p, "penalty": n, "severity": s} for i, p, n, s in rows]
    return lambda _request=None: {"checks": checks, "issues": []}


def test_the_rows_that_need_a_look_are_one_row(monkeypatch):
    monkeypatch.setattr(
        security_advisor,
        "evaluate_security_posture",
        _posture(
            ("admin_mfa", False, 15, "high"),
            ("stale_api_tokens", False, 15, "low"),  # counts, so it needs a look
            ("sec_default_admin", False, 0, "low"),  # a suggestion: not counted
            ("https_transport", True, 0, "info"),
        ),
    )
    assert status_summary._security() == [
        {"id": "security:check", "level": "warning", "kind": "security_look", "subject": "2", "open": "settings"}
    ]
    monkeypatch.setattr(security_advisor, "evaluate_security_posture", _posture(("guest", False, 20, "critical")))
    assert status_summary._security()[0]["level"] == "critical"
    monkeypatch.setattr(security_advisor, "evaluate_security_posture", _posture(("sec_default_admin", False, 0, "low")))
    assert status_summary._security() == []


def test_the_first_time_password_is_not_counted_twice(monkeypatch):
    monkeypatch.setattr(
        security_advisor, "evaluate_security_posture", _posture(("default_password", False, 35, "critical"))
    )
    assert status_summary._security() == []
    assert status_summary._security in status_summary.CHECKS
