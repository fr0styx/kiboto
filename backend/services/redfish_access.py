"""Whether Redfish answers (SET-01).

Redfish hands out the hardware inventory and live readings to monitoring tools. It used to be on
for every install, answer every signed-in account, and show its first page without sign-in. It is
off until an administrator turns it on.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, json_locked, read_json

SETTINGS_FILE = os.path.join(DATA_DIR, "redfish.json")


def _settings() -> dict[str, Any]:
    data = read_json(SETTINGS_FILE, {})
    return data if isinstance(data, dict) else {}


def enabled() -> bool:
    return bool(_settings().get("enabled", False))


@json_locked(lambda *a, **k: SETTINGS_FILE)
def set_enabled(on: bool) -> bool:
    atomic_write_json(SETTINGS_FILE, {**_settings(), "enabled": bool(on)})  # the install's id stays
    return bool(on)


def _valid(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


@json_locked(lambda *a, **k: SETTINGS_FILE)
def _new_uuid() -> str:
    kept = _valid(_settings().get("uuid"))  # another request may have made it meanwhile
    if kept:
        return kept
    made = str(uuid.uuid4())
    atomic_write_json(SETTINGS_FILE, {**_settings(), "uuid": made})
    return made


def system_uuid() -> str:
    """This install's own id for Redfish, made once and kept. Every Kiboto used to answer with the
    same id, so a monitoring tool that tells systems apart by it saw two NAS as one."""
    return _valid(_settings().get("uuid")) or _new_uuid()
