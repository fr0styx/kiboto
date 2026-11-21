"""The household's shared folders, as the places where Kiboto may change or delete many files at once."""

import os


def in_a_shared_folder(path: str) -> bool:
    """Whether `path` is one of the household's shared folders or inside one. Files may browse
    all of /mnt, and below a pool's top lie appdata, system, domains and isos, whose files belong
    to the system on purpose. share_mounts leaves those out, and the share that holds Kiboto's own
    data. False when the storage platform does not answer."""
    from backend.services.app_catalog import share_mounts

    try:
        roots = [os.path.realpath(mp).rstrip(os.sep) for mp in share_mounts().values()]
    except (OSError, RuntimeError, ValueError):
        return False
    real = os.path.realpath(path)
    return any(root and (real == root or real.startswith(root + os.sep)) for root in roots)
