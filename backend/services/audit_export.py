"""The security log as a file to keep outside the NAS (re-audit 19 Nov 2026, R3).

A record of who signed in and who changed what is worth most when it is somewhere the NAS's own
administrator cannot quietly edit it. The export is plain CSV that any spreadsheet opens.
"""

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

from backend.services.known_devices import describe

COLUMNS = ("time_utc", "event", "result", "person", "address", "device", "details")
MAX_ROWS = 20000


def safe_cell(value: Any) -> str:
    """A spreadsheet runs a cell that starts with = + - or @ as a formula: such text gets a quote."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _time(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(float(ts), UTC).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def csv_of(rows: list[dict[str, Any]]) -> str:
    """The rows of the security log (as query_security_audit_logs gives them), newest first."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for r in rows:
        details = r.get("details") or {}
        writer.writerow(
            [
                _time(r.get("timestamp")),
                safe_cell(r.get("event_type")),
                safe_cell(r.get("status")),
                safe_cell(r.get("actor_username")),
                safe_cell(r.get("actor_ip")),
                safe_cell(describe(str(r.get("actor_user_agent") or ""))),
                safe_cell(json.dumps(details, ensure_ascii=False, sort_keys=True) if details else ""),
            ]
        )
    return "﻿" + out.getvalue()  # the mark tells Excel the file is UTF-8
