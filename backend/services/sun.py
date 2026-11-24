"""Today's and tomorrow's sunrise and sunset where the NAS is, for the look's "By sunset" mode
(APP-D): light from sunrise to sunset, dark after.

Where the NAS is comes from its time zone: the IANA zone table (zone1970.tab) gives every zone a
place, its main city, close enough to say when it gets dark. Nothing is asked of the internet and
no address is kept. The times come from the sunrise equation (NOAA's simplification), a minute or
two from the almanac, which is plenty for a page's colours.
"""

from __future__ import annotations

import datetime as dt
import math
import os
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TABLES = ("/usr/share/zoneinfo/zone1970.tab", "/usr/share/zoneinfo/zone.tab")
_SUN_BELOW = -0.833  # degrees: the sun's upper edge on the horizon, with the air's bending


def _degrees(text: str) -> float:
    """A zone table coordinate: ±DDMM, ±DDDMM, or the same with seconds."""
    sign = -1.0 if text[0] == "-" else 1.0
    digits = text[1:]
    if len(digits) in (4, 5):
        whole, minutes, seconds = digits[:-2], digits[-2:], "0"
    else:
        whole, minutes, seconds = digits[:-4], digits[-4:-2], digits[-2:]
    return sign * (int(whole) + int(minutes) / 60 + int(seconds) / 3600)


def place_of(zone: str, tables: tuple[str, ...] = TABLES) -> tuple[float, float] | None:
    """(latitude, longitude) of a time zone's main city, or None for a zone without a place (UTC)."""
    for path in tables:
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        for line in lines:
            parts = line.split("\t")
            if line.startswith("#") or len(parts) < 3 or parts[2] != zone:
                continue
            coords = parts[1]
            cut = max(coords.rfind("+"), coords.rfind("-"))  # the longitude's sign
            if cut > 0:
                return _degrees(coords[:cut]), _degrees(coords[cut:])
    return None


def sun_times(day: dt.date, lat: float, lon: float) -> tuple[float | None, float | None, str]:
    """(sunrise, sunset) as Unix times for `day` (UTC calendar), and "" or "day"/"night" when the
    sun does not rise or set there that day."""
    rad = math.radians
    julian = day.toordinal() + 1721424.5 + 0.5  # the day's noon
    n = math.ceil(julian - 2451545.0 + 0.0008)
    mean_solar = n - lon / 360
    anomaly = (357.5291 + 0.98560028 * mean_solar) % 360
    centre = 1.9148 * math.sin(rad(anomaly)) + 0.02 * math.sin(rad(2 * anomaly)) + 0.0003 * math.sin(rad(3 * anomaly))
    ecliptic = (anomaly + centre + 180 + 102.9372) % 360
    transit = 2451545.0 + mean_solar + 0.0053 * math.sin(rad(anomaly)) - 0.0069 * math.sin(rad(2 * ecliptic))
    declination = math.asin(math.sin(rad(ecliptic)) * math.sin(rad(23.4397)))
    cos_hour = (math.sin(rad(_SUN_BELOW)) - math.sin(rad(lat)) * math.sin(declination)) / (
        math.cos(rad(lat)) * math.cos(declination)
    )
    if cos_hour < -1:
        return None, None, "day"
    if cos_hour > 1:
        return None, None, "night"
    hour = math.degrees(math.acos(cos_hour)) / 360

    def unix(j: float) -> float:
        return round((j - 2440587.5) * 86400, 1)

    return unix(transit - hour), unix(transit + hour), ""


def zone_now() -> str:
    """The household's time zone (General), else the container's."""
    try:
        from backend.services.identity import get_identity

        zone = str(get_identity().get("timezone") or "")
    except (OSError, ValueError):
        zone = ""
    return zone or os.environ.get("TZ", "")


def today(zone: str | None = None, now: dt.datetime | None = None, tables: tuple[str, ...] = TABLES) -> dict[str, Any]:
    """Sunrise and sunset for today and tomorrow in the NAS's time zone, as the page uses them."""
    zone = zone if zone is not None else zone_now()
    place = place_of(zone, tables) if zone else None
    if place is None:
        return {"zone": zone, "known": False, "days": []}
    try:
        local = (now or dt.datetime.now(dt.UTC)).astimezone(ZoneInfo(zone))
    except (ZoneInfoNotFoundError, ValueError):
        return {"zone": zone, "known": False, "days": []}
    days = []
    for offset in (0, 1):
        day = local.date() + dt.timedelta(days=offset)
        rise, set_, polar = sun_times(day, *place)
        days.append({"date": day.isoformat(), "sunrise": rise, "sunset": set_, "polar": polar})
    return {"zone": zone, "known": True, "days": days}
