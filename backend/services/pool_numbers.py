"""How full each storage pool is, for dashboards outside Kiboto (the metrics page, Home Assistant).

Read from the storage platform's own cached list: no drive is woken, and it costs about a
millisecond, so it can be asked on every scrape."""

import re
from typing import Any

from backend.config import logger
from backend.services.pool_alerts import GOOD_POOL


def pool_numbers() -> list[dict[str, Any]]:
    """[{key, name, type, total, used, free (bytes), pct, healthy}] for each pool that has a size.
    A pool that reports no size (an empty slot, or one that is not mounted) is left out."""
    try:
        from backend.hardware.pal_storage import get_storage_platform

        pools = list(get_storage_platform().list_pools())
    except (OSError, RuntimeError, ValueError):
        logger.debug("[PoolNumbers] could not read the pools", exc_info=True)
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in pools:
        total = int(getattr(p, "total_bytes", 0) or 0)
        if total <= 0:
            continue
        used = int(getattr(p, "used_bytes", 0) or 0)
        free = getattr(p, "free_bytes", None)
        name = str(getattr(p, "name", "") or getattr(p, "id", "") or "pool")
        key = re.sub(r"[^a-z0-9]+", "_", str(getattr(p, "id", "") or name).lower()).strip("_") or "pool"
        while key in seen:  # two pools must not share a sensor
            key += "_2"
        seen.add(key)
        out.append(
            {
                "key": key,
                "name": name,
                "type": str(getattr(p, "fs_type", "") or ""),
                "total": total,
                "used": used,
                "free": int(free) if isinstance(free, (int, float)) else max(0, total - used),
                "pct": round(used * 100.0 / total, 1),
                "healthy": str(getattr(p, "status", "HEALTHY") or "HEALTHY").upper() in GOOD_POOL,
            }
        )
    return out


def totals(pools: list[dict[str, Any]]) -> dict[str, Any] | None:
    """All pools together, or None when there is none."""
    total = sum(p["total"] for p in pools)
    if total <= 0:
        return None
    used = sum(p["used"] for p in pools)
    return {"total": total, "used": used, "free": sum(p["free"] for p in pools), "pct": round(used * 100.0 / total, 1)}
