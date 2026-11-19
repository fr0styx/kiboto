"""Re-audit R3: the security log can be saved as a CSV file."""

import csv
import io

from backend.services import audit_export


def _login(client):
    res = client.post("/api/auth/login", json={"password": "admin"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _rows(text):
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text[1:])))


def test_rows_become_csv_with_a_named_device_and_utc_time():
    text = audit_export.csv_of(
        [
            {
                "timestamp": 1763500000,
                "event_type": "auth.login.success",
                "status": "success",
                "actor_username": "mara",
                "actor_ip": "192.168.1.20",
                "actor_user_agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/141.0 Safari/537.36",
                "details": {"method": "password"},
            },
            {"timestamp": "never", "event_type": "user.created", "status": "success", "details": {}},
        ]
    )
    rows = _rows(text)
    assert tuple(rows[0]) == audit_export.COLUMNS
    assert rows[1] == [
        "2025-11-18 21:06:40",
        "auth.login.success",
        "success",
        "mara",
        "192.168.1.20",
        "Chrome on Windows",
        '{"method": "password"}',
    ]
    assert rows[2][0] == "" and rows[2][3] == "" and rows[2][6] == ""


def test_text_a_spreadsheet_would_run_is_defused():
    for bad in ("=1+1", "+cmd", "-2", "@SUM(A1)"):
        assert audit_export.safe_cell(bad) == "'" + bad
    assert audit_export.safe_cell("mara") == "mara" and audit_export.safe_cell(None) == ""
    rows = _rows(audit_export.csv_of([{"timestamp": 1, "event_type": "x", "actor_username": '=HYPERLINK("http://x")'}]))
    assert rows[1][3].startswith("'=")


def test_the_route_needs_the_audit_right_and_records_the_export(client):
    assert client.get("/api/auth/audit/export").status_code in (401, 403)
    h = _login(client)
    res = client.get("/api/auth/audit/export", headers=h)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "kiboto-security-log-" in res.headers["content-disposition"]
    rows = _rows(res.text)
    assert tuple(rows[0]) == audit_export.COLUMNS and len(rows) > 1
    logs = client.get("/api/auth/audit?limit=5", headers=h).json()["audit_logs"]
    assert any(r["event_type"] == "audit.exported" for r in logs)
