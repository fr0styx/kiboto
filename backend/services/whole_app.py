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


def _go_back(done: list[dict[str, Any]]) -> list[str]:
    """Puts the parts already updated back on their old containers (kept stopped and renamed),
    the last updated first. Returns the names that could not be put back."""
    from backend.services.container_mutator import docker_request
    from backend.services.docker_updates import mark_update_pending

    stuck: list[str] = []
    for res in reversed(done):
        name = str(res.get("target_name") or "")
        try:
            docker_request("DELETE", f"/containers/{res['new_id']}?v=false&force=true")
            st, _ = docker_request("POST", f"/containers/{res['old_id']}/rename?name={name}")
            if st != 204:
                raise RuntimeError(f"rename answered {st}")
            st, _ = docker_request("POST", f"/containers/{res['old_id']}/start")
            if st not in (204, 304):
                raise RuntimeError(f"start answered {st}")
            mark_update_pending(name)
        except _FAILS as e:
            logger.error("[Apps] Could not put %s back on its old version: %s", name, e)
            stuck.append(name)
    return stuck


def _drop_old(done: list[dict[str, Any]]) -> None:
    """The whole app runs its new versions: the old containers kept for going back can go."""
    from backend.services.container_mutator import docker_request

    for res in done:
        try:
            docker_request("DELETE", f"/containers/{res['old_id']}?v=false&force=true")
        except _FAILS as e:
            logger.warning("[Apps] Old container %s left behind: %s", res.get("backup_name"), e)


def start_app_update(stack: str, owner: str | None = None) -> dict[str, Any]:
    """Updates every part of an app that has a newer image, one after the other in start order,
    as a job. Each part must keep running on its new version; a part that fails stops the rest and
    the parts already updated go back to their old versions, so the app never runs half updated."""
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
        done: list[dict[str, Any]] = []
        for i, name in enumerate(parts):
            job_manager.update(job.id, detail=f"Updating {name}", percent=float(100 * i / len(parts)))
            try:
                done.append(update_single_container(name, keep_backup=True) or {})
            except _FAILS as e:
                error = f"{name} could not be updated: {str(e).rstrip('.')}."
                if done:
                    job_manager.update(job.id, detail="Going back to the old versions")
                    stuck = _go_back(done)
                    error += (
                        f" Could not put back: {', '.join(stuck)}."
                        if stuck
                        else " The parts already updated went back to their old versions."
                    )
                add_event("warning", "App not updated", f"{stack}: {error}")
                job_manager.finish(job.id, "error", error)
                return
        _drop_old(done)
        add_event("success", "App updated", f"{stack}: {', '.join(parts)}.")
        job_manager.finish(job.id, "done")

    threading.Thread(target=run, daemon=True, name=f"app-update-{stack}").start()
    return {"status": "started", "job": job.id, "parts": parts}
