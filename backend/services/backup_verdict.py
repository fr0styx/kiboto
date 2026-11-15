"""Are your files safe? (Backup 1, SET-21 stage 1): one answer for the top of Backup, from the same
copies the Overview counts, with what needs a look and the backup it is about.

Fine (Backup decision 1 A): at least one copy outside this Kiboto that is fresh by its allowance (a
USB disk 7 days, other places 3), and nothing to look at. Failed: a backup's last run failed.
Needs a look: anything else that is set up. None: nothing set up yet.

The lines also cover what the old status table watched (stage 1b): a backup job that failed, a
snapshot schedule that failed or fell behind, and a monthly disk check that is late or found errors.
"""

import time
from typing import Any

from backend.config import logger
from backend.services.protection_status import FRESH_SECS, copies, kind_of

USB_FRESH_SECS = 7 * 86400


def allowance(kind: str) -> int:
    """How old a copy may be and still count as current: a USB disk is plugged in less often."""
    return USB_FRESH_SECS if kind == "usb" else FRESH_SECS


def _repo_issues(repo: dict[str, Any], now: float) -> list[dict[str, Any]]:
    """What needs a look in one off-site backup, worst first."""
    who = {"name": repo.get("name") or repo.get("id"), "id": repo.get("id"), "engine": "offsite"}
    kind = kind_of(str(repo.get("location") or ""))
    out: list[dict[str, Any]] = []
    result = str(repo.get("last_result") or "")
    if result and result != "ok":
        out.append({**who, "kind": "failed", "detail": result[:200]})
    elif repo.get("initialized"):
        last = repo.get("last_backup")
        if not last or now - float(last) > allowance(kind):
            out.append({**who, "kind": "late", "since": last})
    if repo.get("same_disk"):
        out.append({**who, "kind": "same_disk"})
    elif kind == "here":
        out.append({**who, "kind": "here_only"})
    if repo.get("initialized") and not repo.get("kit_saved_at"):
        out.append({**who, "kind": "kit"})
    if int(repo.get("last_unreadable") or 0) > 0:
        out.append({**who, "kind": "unreadable", "count": int(repo["last_unreadable"])})
    drill = str(repo.get("last_drill_result") or "")
    if drill.startswith("failed"):  # "no file small enough to test" is not a failure
        out.append({**who, "kind": "drill", "detail": drill[:200]})
    return out


def _repos() -> list[dict[str, Any]]:
    try:
        from backend.services.offsite_backup import list_repos

        return list_repos()
    except (OSError, ValueError, RuntimeError):
        logger.debug("backup_verdict: off-site backups unreadable", exc_info=True)
        return []


def _protection_rows(now: float) -> list[dict[str, Any]]:
    try:
        from backend.services.protection_jobs import jobs

        return jobs(now)
    except (OSError, ValueError, RuntimeError, ImportError):
        logger.debug("backup_verdict: protection rows unreadable", exc_info=True)
        return []


def _row_issues(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Backup jobs, snapshot schedules and disk checks that need a look. Off-site rows have their own
    lines above; "off", "run by the host" and "not available" are notes, not problems."""
    out: list[dict[str, Any]] = []
    for row in rows:
        who = {"name": row.get("name") or row.get("id"), "id": row.get("id")}
        kind, status = row.get("kind"), row.get("status")
        if kind == "backup" and status == "failed":
            out.append({**who, "engine": "copy", "kind": "failed", "detail": str(row.get("why") or "")[:200]})
        elif kind == "snapshot" and status in ("failed", "overdue"):
            out.append({**who, "engine": "snapshot", "kind": "snap_failed" if status == "failed" else "snap_late"})
        elif kind == "scrub":
            if status == "overdue":
                out.append({**who, "engine": "check", "kind": "check_late"})
            if int(row.get("errors") or 0) > 0:
                out.append({**who, "engine": "check", "kind": "check_errors", "count": int(row["errors"])})
    return out


def verdict(now: float | None = None) -> dict[str, Any]:
    """{level: fine | look | failed | none, newest: {name, kind, when} | None, issues: [...]}."""
    now = now or time.time()
    repos = _repos()
    found = copies()  # every copy outside this Kiboto (off-site, copy jobs, replication)
    issues: list[dict[str, Any]] = []
    for repo in repos:
        issues.extend(_repo_issues(repo, now))
    table = _protection_rows(now)
    rows = _row_issues(table)
    failed_jobs = {i["name"] for i in rows if i["kind"] == "failed"}
    issues.extend(rows)
    set_up = repos or found or any(r.get("kind") in ("backup", "snapshot", "offsite") for r in table)
    for c in found:
        if c.get("engine") == "offsite" or c.get("name") in failed_jobs:
            continue  # its own lines above
        last = c.get("last_ok")
        if not last or now - float(last) > allowance(str(c.get("kind"))):
            issues.append({"name": c.get("name"), "id": None, "engine": c.get("engine"), "kind": "late", "since": last})
    good = [c for c in found if c.get("last_ok")]
    fresh = [c for c in good if now - float(c["last_ok"]) <= allowance(str(c.get("kind")))]
    newest = max(good, key=lambda c: float(c["last_ok"]), default=None)
    if not set_up:
        level = "none"
    elif any(i["kind"] in ("failed", "snap_failed") for i in issues):
        level = "failed"
    elif fresh and not issues:
        level = "fine"
    else:
        level = "look"
    return {
        "level": level,
        "newest": {"name": newest.get("name"), "kind": newest.get("kind"), "when": float(newest["last_ok"])}
        if newest
        else None,
        "issues": issues,
    }
