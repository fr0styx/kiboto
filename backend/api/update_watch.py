"""The daily update check (Settings decision 5): once a day, unless turned off, ask whether a newer
Kiboto is ready for this server's channel, mark Settings and send one alert per new version."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth import require_scope
from backend.config import logger
from backend.services import update_watch

router = APIRouter(tags=["System"])
FIRST_WAIT_SECS = 300  # not in the busy first minutes after a start
LOOK_EVERY_SECS = 3600


class UpdateWatchIn(BaseModel):
    daily: bool


@router.get("/system/update-watch", dependencies=[Depends(require_scope("system:view"))])
def get_update_watch() -> dict[str, Any]:
    st = update_watch.state()
    return {"daily": st["daily"], "last_check": st["last_check"], "available": st["available"], "latest": st["latest"]}


@router.put("/system/update-watch", dependencies=[Depends(require_scope("system:config"))])
def put_update_watch(req: UpdateWatchIn) -> dict[str, Any]:
    st = update_watch.set_daily(req.daily)
    return {"daily": st["daily"], "last_check": st["last_check"], "available": st["available"], "latest": st["latest"]}


def _announce(version: str) -> None:
    from backend.services.notifications import send_notification

    send_notification(
        title="A Kiboto update is ready",
        message=f"Version {version} is ready to install. Open Settings, then General, to update.",
        level="info",
        event_type="update",
        dedup_key=f"kiboto-update-{version}",
        text={
            "title_key": "alert.update_ready.title",
            "msg_key": "alert.update_ready.msg",  # gitleaks:allow (a text key)
            "params": {"version": version},
        },
    )


async def check_once(now: float | None = None) -> str:
    """One check, recorded; returns the version announced now ("" for none)."""
    from backend import settings
    from backend.api.system import check_system_updates

    now = time.time() if now is None else now
    try:
        result = await check_system_updates(force=True, channel=str(settings.current("update_channel") or "stable"))
    except (OSError, ValueError, RuntimeError) as e:  # recorded, and tried again tomorrow
        logger.debug("[UpdateWatch] check failed: %s", e)
        result = {"error": str(e)}
    version = update_watch.record(result, now)
    if version:
        await asyncio.to_thread(_announce, version)
    return version


async def watch_loop() -> None:
    """Started with the app; looks once an hour whether a day has passed since the last check."""
    await asyncio.sleep(FIRST_WAIT_SECS)
    while True:
        if update_watch.due(time.time()):
            await check_once()
        await asyncio.sleep(LOOK_EVERY_SECS)
