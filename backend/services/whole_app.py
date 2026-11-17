"""Whole-app actions (Apps decision 2): an app of several containers (a Compose project) is
updated and removed as one, so the Apps window can show one row per app."""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_FAILS = (ValueError, OSError, RuntimeError, KeyError, TypeError)


def remove_app(stack: str, keep_backup: bool = True) -> dict[str, Any]:
    """Removes every part of an app, the last-started first. With keep_backup (the default) one
    archive of the whole app is made first; if that fails nothing is removed."""
    from backend.services.app_backup import create_stack_backup
    from backend.services.docker_cleanup import destroy_container
    from backend.services.docker_stacks import app_details

    details = app_details(stack)
    backup = create_stack_backup(stack, reason="uninstall") if keep_backup else None
    removed: list[str] = []
    failed: list[dict[str, str]] = []
    for c in reversed(details["containers"]):
        name = str(c.get("name") or c.get("id"))
        try:
            destroy_container(str(c.get("id")), force=True, archive_data=False)
            removed.append(name)
        except _FAILS as e:
            failed.append({"name": name, "error": f"{e}"})
    logger.info("[Apps] Removed the app %s: %d parts, %d failed", stack, len(removed), len(failed))
    return {
        "success": not failed,
        "app": stack,
        "removed": removed,
        "failed": failed,
        "backup": {"id": backup["id"], "filename": backup["filename"]} if backup else None,
    }


def parts_with_updates(stack: str) -> list[str]:
    """The parts of an app whose image has a newer version, in start order (from the last check)."""
    from backend.services.docker_stacks import app_details
    from backend.services.docker_updates import check_all_container_updates

    details = app_details(stack)
    known = (check_all_container_updates(force=False) or {}).get("containers") or {}
    out = []
    for c in details["containers"]:
        entry = known.get(c.get("name")) or known.get(c.get("id")) or {}
        if entry.get("has_update"):
            out.append(str(c.get("name")))
    return out


def start_app_update(stack: str, owner: str | None = None) -> dict[str, Any]:
    """Updates every part of an app that has a newer image, one after the other in start order,
    as a job. Each part is replaced with its own go-back; a part that fails stops the rest."""
    from backend.services.docker_updates import update_single_container
    from backend.services.jobs import job_manager
    from backend.state import add_event

    parts = parts_with_updates(stack)
    if not parts:
        return {"status": "up_to_date", "parts": []}
    job = job_manager.register(
        "app_update",
        f"Update {stack}",
        owner=owner,
        title_id="jobs.t.app_update",
        title_params={"name": stack},
    )

    def run() -> None:
        done: list[str] = []
        for i, name in enumerate(parts):
            job_manager.update(job.id, detail=f"Updating {name}", percent=float(100 * i / len(parts)))
            try:
                update_single_container(name)
            except _FAILS as e:
                error = f"{name} could not be updated: {e}"
                if done:
                    error += f" Already updated: {', '.join(done)}."
                add_event("warning", "App not updated", f"{stack}: {error}")
                job_manager.finish(job.id, "error", error)
                return
            done.append(name)
        add_event("success", "App updated", f"{stack}: {', '.join(done)}.")
        job_manager.finish(job.id, "done")

    threading.Thread(target=run, daemon=True, name=f"app-update-{stack}").start()
    return {"status": "started", "job": job.id, "parts": parts}
