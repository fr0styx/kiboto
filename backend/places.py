"""Where Kiboto puts people's home folders when the storage has a say.

On a machine set up for Kiboto they go on its first pool, never on the system disk
(services/pool_places.py chooses the place once a pool exists and writes it down here, so it never
moves); elsewhere, and until then, in the storage folder of this install."""

import os

from backend import config
from backend.fsutil import atomic_write_json, json_locked, read_json


def _file() -> str:
    return os.path.join(config.DATA_DIR, "storage", "places.json")


def recorded(kind: str) -> str:
    data = read_json(_file(), {}) if os.path.exists(_file()) else {}
    value = data.get(kind) if isinstance(data, dict) else ""
    return value if isinstance(value, str) and value.startswith("/") else ""


@json_locked(lambda *a, **k: _file())
def record(kind: str, path: str) -> None:
    data = read_json(_file(), {}) if os.path.exists(_file()) else {}
    data = data if isinstance(data, dict) else {}
    data[kind] = path
    os.makedirs(os.path.dirname(_file()), exist_ok=True)
    atomic_write_json(_file(), data)


def homes_root() -> str:
    return recorded("homes") or os.path.join(getattr(config, "POOL_PATH", "/mnt/user"), "homes")
