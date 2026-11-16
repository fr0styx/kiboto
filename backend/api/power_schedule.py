"""Scheduled power off and wake-up (audit A10). See backend/services/power_schedule.py."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.services import power_schedule

router = APIRouter(tags=["System"])


class PowerScheduleIn(BaseModel):
    enabled: bool = False
    off_at: str = Field("01:00", max_length=5)
    wake_at: str = Field("07:00", max_length=5)
    days: list[int] = [0, 1, 2, 3, 4, 5, 6]


@router.get("/system/power-schedule", dependencies=[Depends(require_scope("system:view"))])
def get_power_schedule() -> dict[str, Any]:
    return power_schedule.public_state()


@router.put("/system/power-schedule", dependencies=[Depends(require_scope("system:power"))])
def put_power_schedule(req: PowerScheduleIn) -> dict[str, Any]:
    try:
        return power_schedule.save(req.enabled, req.off_at, req.wake_at, req.days)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _power_off() -> bool:
    """The same host shutdown as Settings: virtual machines first, then the NAS."""
    from backend.api.system import machines_first, trigger_power_action

    machines_first(False)
    return trigger_power_action("shutdown")


async def power_schedule_loop() -> None:
    """Once a minute; does nothing while the schedule is off."""
    while True:
        await asyncio.sleep(power_schedule.sleep_seconds())
        await asyncio.to_thread(power_schedule.loop_once, _power_off)
