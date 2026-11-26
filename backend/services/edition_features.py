"""What this edition of Kiboto can do, from the feature table.

docs/feature-matrix.json is the one source of what Kiboto Companion (beside a NAS system, or on plain
Linux) and Kiboto OS can each do; scripts/feature_matrix.py writes the features the app reads into
backend/edition_features.json. A card asks here, so the app says what GitHub and the website say:
"still being checked" where the table says so, "your NAS system does this" beside a NAS system."""

import functools
import json
import os

from backend import runtime
from backend.config import logger

FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "edition_features.json")


def column() -> str:
    """The table's column for this install: "os", "linux" (Companion on plain Linux, or Kiboto
    started by hand) or "beside" (Companion beside Unraid, TrueNAS and the like)."""
    if runtime.managed_host():
        return "os"
    try:
        from backend.hardware.pal_storage import get_storage_platform

        platform = get_storage_platform().get_platform_type().value
    except (ImportError, OSError, RuntimeError, ValueError, AttributeError):
        return "linux"
    return "linux" if platform == "generic_linux" else "beside"


@functools.lru_cache(maxsize=1)
def _table() -> dict[str, dict[str, str]]:
    try:
        with open(FILE, encoding="utf-8") as f:
            features = json.load(f).get("features", {})
    except (OSError, ValueError) as e:
        logger.warning("[Edition] The feature table could not be read: %s", e)
        return {}
    return features if isinstance(features, dict) else {}


def state(feature: str, where: str = "") -> str:
    """The feature's state here: yes, partly, view, host, soon, check or no; "" when unknown."""
    return str(_table().get(feature, {}).get(where or column(), ""))


def here() -> dict[str, str]:
    where = column()
    return {name: str(cols.get(where, "")) for name, cols in _table().items()}
