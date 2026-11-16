"""
Kiboto - Chassis Visualizer & Layout API Routes
"""

import time
from typing import Any

from fastapi import APIRouter, Depends

from backend.auth import require_scope
from backend.hardware.chassis import ChassisBayMapRequest, ChassisEngine
from backend.state import Z_STATE

router = APIRouter(prefix="/chassis", tags=["Chassis Visualizer & Layout"])


@router.get("/config", dependencies=[Depends(require_scope("hardware:read", "storage:read", "system:view"))])
def get_chassis_config():
    """
    Returns dynamic chassis layout configuration, detected bays, populated disks,
    and motherboard M.2 NVMe slots; each drive carries Drive Health's stored verdict (SET-22).
    """
    return with_verdicts(ChassisEngine.get_chassis_status())


def verdict_of(dev: str, verdicts: dict[str, Any], now: float) -> dict[str, str]:
    """Drive Health's last verdict for a drive, as Drive Health words it (label_key), or nothing
    when there is none recent enough. Read from memory: no drive is woken."""
    from backend.services.status_summary import VERDICT_MAX_AGE

    v = verdicts.get(dev) or {}
    if not v or now - float(v.get("ts") or 0) >= VERDICT_MAX_AGE:
        return {}
    verdict = str(v.get("verdict") or "unknown")
    if verdict in ("now", "soon"):
        key = f"{verdict}_{'replace' if v.get('kind') == 'replace' else 'other'}"
    elif verdict in ("watch", "ok"):
        key = verdict
    else:
        return {}
    return {"verdict": verdict, "verdict_label_key": key}


def with_verdicts(status: dict[str, Any]) -> dict[str, Any]:
    """The bay picture's drives, each with its stored verdict (SET-22 Storage 3)."""
    verdicts = Z_STATE.smart.snapshot("verdicts")
    now = time.time()
    for bay in status.get("bays") or []:
        disk = bay.get("disk") if isinstance(bay, dict) else None
        if isinstance(disk, dict) and disk.get("dev"):
            disk.update(verdict_of(disk["dev"], verdicts, now))
    for slot in status.get("nvme_slots") or []:
        nv = slot.get("disk") if isinstance(slot, dict) else None
        if isinstance(nv, dict):
            dev = nv.get("dev") or nv.get("name")
            if dev:
                nv.update(verdict_of(dev, verdicts, now))
    return status


@router.post("/bay_map", dependencies=[Depends(require_scope("storage:admin", "system:config"))])
def save_chassis_bay_map(request: ChassisBayMapRequest):
    """
    Saves user-customized chassis profile, total bays, and drag-and-drop bay slot assignments.
    """
    return ChassisEngine.save_bay_mapping(request)


@router.get("/bridges", dependencies=[Depends(require_scope("hardware:read", "storage:read", "system:view"))])
def get_chassis_bridges():
    """Returns detected hardware platform bridges (Zettlab, Aoostar, Ugreen, CWWK)."""
    return ChassisEngine.get_appliance_bridge_status()
