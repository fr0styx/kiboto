"""People's home folders on the first pool of a machine set up for Kiboto.

The first admin is made at the first start, before there is any pool, and was given a home folder
in the storage folder, which on such a machine is the system disk (hardware/pal/system_disk.py).
Once a pool exists, homes go on it: the place is written down (places.py), and the records of home
folders that were never used (missing or empty) follow it. A home folder with files in it stays.
Settled at every start and after a pool is made."""

import os

from backend import config, places
from backend.config import logger
from backend.hardware.pal import system_disk


def settle() -> dict[str, object]:
    if not system_disk.applies() or places.recorded("homes"):
        return {}
    pool = system_disk.first_pool()
    if not pool:
        return {}
    from backend.users_db import move_unused_homes

    new = os.path.join(pool, "homes")
    places.record("homes", new)
    moved = move_unused_homes(os.path.join(config.POOL_PATH, "homes"), new)
    logger.info("[Users] Home folders are made in %s from now on (%s record(s) moved there)", new, moved)
    return {"homes": new, "moved": moved}
