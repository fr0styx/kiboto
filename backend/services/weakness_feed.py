"""Apps with a weakness that is being attacked right now (owner, 19 Nov 2026; off until turned on).

CISA publishes the list of weaknesses known to be exploited (the KEV catalog). With this check
on, Kiboto downloads that list once a day (nothing about this NAS is sent; the site sees the
home's internet address) and compares it, here, with the apps that are installed.

An app is flagged when the list names its software and the app's image was built before the
weakness was added to the list: that copy predates the public warning, so it may be affected and
should be updated. The list has no version numbers, so the wording stays "may be". An image
built after the warning is taken to carry the fix.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from backend import outside_checks
from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, read_json

logger = logging.getLogger("Kiboto")

FEED_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
STATE_FILE = os.path.join(DATA_DIR, "weakness_feed.json")
EVERY_SECS = 86400
MIN_NAME = 3  # shorter software names match too much


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _epoch(day: str) -> float:
    try:
        return datetime.strptime(day[:10], "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
    except (TypeError, ValueError):
        return 0.0


def compact(feed: dict[str, Any]) -> list[dict[str, Any]]:
    """What the comparison needs from the published list, one row per weakness."""
    rows = []
    for v in feed.get("vulnerabilities") or []:
        product = str(v.get("product") or "")
        vendor = _norm(str(v.get("vendorProject") or "").split(" ")[0])
        first = _norm(product.split(" ")[0]) if product else ""
        # the whole product name, and its first word only when that is the maker's own name
        # ("Plex Media Server" by Plex): "Backup Exec" must not match every image called "backup"
        keys = sorted({k for k in (_norm(product), first if first == vendor else "") if len(k) >= MIN_NAME})
        if not keys or not v.get("cveID"):
            continue
        rows.append(
            {
                "cve": str(v["cveID"]),
                "keys": keys,
                "product": f"{v.get('vendorProject') or ''} {product}".strip(),
                "added": _epoch(str(v.get("dateAdded") or "")),
                "ransomware": str(v.get("knownRansomwareCampaignUse") or "").lower() == "known",
            }
        )
    return rows


def _fetch() -> dict[str, Any]:
    res = httpx.get(FEED_URL, headers={"User-Agent": "Kiboto"}, timeout=30.0, follow_redirects=True)
    res.raise_for_status()
    return res.json()


def stored() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def due(now: float) -> bool:
    return outside_checks.enabled("weakness_feed") and now - float(stored().get("fetched_at") or 0) >= EVERY_SECS


def refresh(now: float | None = None, fetch: Callable[[], dict[str, Any]] | None = None) -> int | None:
    """Downloads the list and keeps the compact copy. The number of weaknesses, or None when the
    check is off or the list could not be fetched (the old copy stays)."""
    if not outside_checks.enabled("weakness_feed"):
        return None
    now = time.time() if now is None else now
    try:
        rows = compact((fetch or _fetch)())
    except (httpx.HTTPError, OSError, ValueError) as e:
        logger.info("weakness feed: the list could not be fetched (%s)", type(e).__name__)
        return None
    atomic_write_json(STATE_FILE, {"fetched_at": now, "entries": rows})
    return len(rows)


def image_name(image: str) -> str:
    """ "lscr.io/linuxserver/plex:latest" -> "plex"; "grafana/grafana@sha256:..." -> "grafana"."""
    ref = str(image or "").split("@")[0]
    last = ref.rsplit("/", 1)[-1]
    return _norm(last.split(":")[0])


def matches(apps: list[dict[str, Any]], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """apps: [{"name", "image", "built"}] (built: when the image was made, epoch). One finding per
    app: the most recently listed weakness its copy predates."""
    by_key: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        for k in e.get("keys") or []:
            by_key.setdefault(k, []).append(e)
    out = []
    for app in apps:
        hits = [
            e for e in by_key.get(image_name(app.get("image", "")), []) if e["added"] > float(app.get("built") or 0)
        ]
        if not hits:
            continue
        newest = max(hits, key=lambda e: e["added"])
        out.append(
            {
                "app": app["name"],
                "cve": newest["cve"],
                "product": newest["product"],
                "added": newest["added"],
                "ransomware": any(e["ransomware"] for e in hits),
                "count": len(hits),
            }
        )
    return sorted(out, key=lambda f: f["app"])


def _built(created: Any) -> float:
    try:
        return datetime.fromisoformat(str(created).replace("Z", "+00:00")[:19] + "+00:00").timestamp()
    except (TypeError, ValueError):
        return 0.0


def installed_apps() -> list[dict[str, Any]]:
    """The installed apps with the day each one's image was built; [] when Docker does not answer."""
    from backend.services import docker_client

    try:
        status, containers = docker_client.request("GET", "/containers/json?all=1", timeout=10.0)
        if status != 200 or not isinstance(containers, list):
            return []
        built: dict[str, float] = {}
        apps = []
        for c in containers:
            image_id = str(c.get("ImageID") or "")
            if image_id and image_id not in built:
                st, info = docker_client.request("GET", f"/images/{image_id}/json", timeout=10.0)
                built[image_id] = _built(info.get("Created")) if st == 200 and isinstance(info, dict) else 0.0
            name = ((c.get("Names") or [""])[0]).lstrip("/") or image_id[:12]
            apps.append({"name": name, "image": str(c.get("Image") or ""), "built": built.get(image_id, 0.0)})
        return apps
    except docker_client.DockerError:
        return []


def findings() -> list[dict[str, Any]]:
    """Installed apps that may be affected. [] while the check is off or the list was never fetched."""
    if not outside_checks.enabled("weakness_feed"):
        return []
    entries = stored().get("entries") or []
    return matches(installed_apps(), entries) if entries else []
