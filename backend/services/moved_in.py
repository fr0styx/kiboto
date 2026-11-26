"""Settings brought from another install, fitted to this machine's pools (Kiboto OS).

Kiboto Companion often saw one pool as its whole storage folder (on TrueNAS, /mnt/tank as
/mnt/storage), so its shared folders say /mnt/storage/photos. On Kiboto OS each pool is a folder of
its own in the storage folder (/mnt/storage/tank/photos), and the storage folder itself is on the
system disk. After such settings are put in place, a share whose folder is not there is pointed at
the one pool that holds a folder by that path. Nothing is moved or made. A share whose folder is on
no pool, or on two, stays as it was, is named in the log, and is tried again at the next start and
when a pool is imported.

The people come along with their sign-in passwords, kept only as hashes that Samba cannot use. So on
Kiboto OS each person's Windows and Mac shares open again once they have signed in to Kiboto after
the move: the password they sign in with becomes their share password, once. Never for a person with
two-factor sign-in (SEC-28): they get a share password of its own, as before."""

import contextlib
import os
from typing import Any

from backend import runtime
from backend.config import DATA_DIR, POOL_PATH, logger
from backend.errors import SaidError
from backend.fsutil import atomic_write_json, locked_json, read_json

FLAG = ".fit-shares-after-restore"
SMB_AT_SIGN_IN = ".smb-at-sign-in.json"  # who has had their share password set since the move
_restored_at_start = [False]  # settings from a backup were put in place at this start


def mark(data_dir: str = "") -> bool:
    """After settings from a backup were put in place: on Kiboto OS their shares get fitted."""
    if not runtime.managed_host():
        return False
    with open(os.path.join(data_dir or DATA_DIR, FLAG), "w", encoding="utf-8") as f:
        f.write("1\n")
    atomic_write_json(os.path.join(data_dir or DATA_DIR, SMB_AT_SIGN_IN), {"done": []})
    _restored_at_start[0] = True
    return True


def restored_at_this_start() -> bool:
    """Whether settings from a backup were put in place at this start on Kiboto OS: the apps whose
    folders are in the apps' folder then come back, as after a restore from the copy on the pools."""
    return _restored_at_start[0]


def pending(data_dir: str = "") -> bool:
    return os.path.isfile(os.path.join(data_dir or DATA_DIR, FLAG))


def _pools(root: str) -> list[str]:
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [n for n in names if not n.startswith(".") and os.path.ismount(os.path.join(root, n))]


def place(path: str, root: str, pools: list[str]) -> str:
    """Where the folder of a share that is not there is on this machine's pools; "" when it is
    there, outside the storage folder, already on a pool, or on no pool or two."""
    root = root.rstrip("/")
    if not root or not path.startswith(root + "/") or os.path.isdir(path):
        return ""
    rel = os.path.relpath(path, root)
    if rel.startswith("..") or rel.split("/")[0] in pools:
        return ""
    found = []
    for pool in pools:
        there = os.path.join(root, pool, rel)
        if os.path.isdir(there) and not os.path.islink(there):
            found.append(there)
    return found[0] if len(found) == 1 else ""


def fit(
    data_dir: str = "", root: str = "", pools: list[str] | None = None, samba: Any = None, nfs: Any = None
) -> list[tuple[str, str]]:
    """Points each share whose folder is not there at the pool that holds it. Returns (before, now)."""
    data_dir, root = data_dir or DATA_DIR, root or POOL_PATH
    pools = _pools(root) if pools is None else pools
    if samba is None:
        from backend.services.samba_engine import get_samba_engine

        samba = get_samba_engine()
    if nfs is None:
        from backend.services.nfs_engine import get_nfs_engine

        nfs = get_nfs_engine()
    changed: list[tuple[str, str]] = []
    left: list[str] = []
    for share in samba.list_shares():
        new = place(share.path, root, pools)
        if new:
            changed.append((share.path, new))
            samba.add_or_update_share(share.model_copy(update={"path": new}))
        elif not os.path.isdir(share.path):
            left.append(share.name)
    for rule in nfs.list_exports():
        new = place(rule.path, root, pools)
        if new:
            changed.append((rule.path, new))
            nfs.add_or_update_export(rule.model_copy(update={"path": new}))
        elif not os.path.isdir(rule.path):
            left.append(rule.name)
    for before, now in changed:
        logger.warning("[Move in] The shared folder %s is %s on this machine", before, now)
    if left:
        logger.warning(
            "[Move in] Not found on a pool yet: %s (tried again when a pool is imported)", ", ".join(sorted(set(left)))
        )
    else:
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(data_dir, FLAG))
    return changed


def fit_if_pending(data_dir: str = "") -> list[tuple[str, str]]:
    """At the start and after a pool is imported: fits the shares while settings from a backup wait for it."""
    if not pending(data_dir):
        return []
    try:
        return fit(data_dir)
    except (OSError, ValueError, RuntimeError, SaidError) as e:  # never stops the start or the import
        logger.error("[Move in] The shared folders could not be fitted to this machine: %s", e)
        return []


def smb_at_sign_in(username: str, password: str, data_dir: str = "", samba: Any = None) -> bool:
    """After a move, at a person's first sign-in without two-factor: their share password is set
    from the password they signed in with. True when it was set now."""
    path = os.path.join(data_dir or DATA_DIR, SMB_AT_SIGN_IN)
    if not os.path.isfile(path):
        return False
    with locked_json(path):
        done = read_json(path, {}).get("done")
        if not isinstance(done, list) or username in done:
            return False
        if samba is None:
            from backend.services.samba_engine import get_samba_engine

            samba = get_samba_engine()
        try:
            ok = bool(samba.sync_samba_user(username=username, password=password))
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("[Move in] The share password of %s could not be set: %s", username, e)
            return False
        if ok:
            atomic_write_json(path, {"done": sorted({*done, username})})
            logger.info("[Move in] %s can open their shares again", username)
        return ok
