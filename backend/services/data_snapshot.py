"""
Pre-update snapshots of the Kiboto data folder (OPS-03).

The updater takes one right after stopping the old container and restores it
when it rolls back, so the previous version never runs against databases the
new version already migrated. Snapshots live in data/backups/pre-update/; the
newest KEEP are kept.

Not included: the AI search index (rag_index.db, rebuildable and large),
caches, and the backups folder itself.
"""

import json
import logging
import os
import re
import shutil
import sqlite3
import stat
import time
from typing import Any, Optional

from backend import legacy_names
from backend import settings as _settings
from backend.fsutil import atomic_write_json, read_json

logger = logging.getLogger("kiboto.data_snapshot")

SNAPSHOT_SUBDIR = os.path.join("backups", "pre-update")
KEEP = 3  # newest snapshots kept; the newest one taken from a Stable build is kept as well (OPS-5)
LAST_RUN = "last_run.json"  # the build that last ran on this data folder (OPS-4)
RECENT_SNAPSHOT_SECS = 3600
INCLUDE_DIRS = ("rclone", "samba", "sftp", "nfs", "stacks")
SKIP_PREFIXES = ("rag_index.db",)
SKIP_SUFFIXES = (".png", ".bmp", ".jpg", ".py", ".tmp", "-wal", "-shm", ".lock")
MANIFEST = "manifest.json"


def _wanted_file(name: str) -> bool:
    return not name.startswith(SKIP_PREFIXES) and not name.endswith(SKIP_SUFFIXES)


def _copy_db(src: str, dst: str) -> None:
    """Consistent copy of a SQLite file (includes anything still in its WAL); encrypted files stay encrypted."""
    from backend import db_crypto

    if db_crypto.applies_to(src) and db_crypto.is_encrypted(src) and not db_crypto.enabled():
        # The updater's helper has no data key (AI-20). Kiboto is stopped while it snapshots, so the
        # encrypted file is copied as it is; unsaved changes in its WAL would be lost, so refuse then.
        wal = src + "-wal"
        if os.path.exists(wal) and os.path.getsize(wal) > 0:
            raise RuntimeError(f"{os.path.basename(src)} has unsaved changes in its WAL")
        shutil.copy2(src, dst)
        return
    db_crypto.copy(src, dst)


def current_build() -> str:
    """This build: version plus short commit (edge builds share a version number)."""
    from backend import __version__

    commit = _settings.current("build_commit")[:7]
    return f"{__version__}+{commit}" if commit else __version__


def is_stable_tag(image_tag: str) -> bool:
    """latest, stable or a version tag (1.9, 1.9.4, v1.9.4, with or without -core)."""
    last = image_tag.split("/")[-1]
    tag = last.rsplit(":", 1)[1] if ":" in last else "latest"
    tag = tag.removesuffix("-core")
    return tag in ("latest", "stable") or bool(re.fullmatch(r"v?\d+\.\d+(\.\d+)?", tag))


def snapshot_if_build_changed(data_dir: str, build: str | None = None) -> str | None:
    """At startup: if a different build ran on this data folder last, and the in-app updater
    didn't just snapshot it, take a snapshot before anything is migrated. Updates from the
    Unraid Docker tab or `docker compose pull` get one too (OPS-4)."""
    build = build or current_build()
    path = os.path.join(data_dir, LAST_RUN)
    prev = str((read_json(path, {}) or {}).get("build") or "")
    taken = None
    if prev and prev != build:
        now = time.time()
        recent = [
            s
            for s in list_snapshots(data_dir)
            if s.get("to_build") == build and now - float(s.get("created_at") or 0) < RECENT_SNAPSHOT_SECS
        ]
        if not recent:
            taken = take_snapshot(
                data_dir,
                label=f"from-{prev}",
                extra={"kind": "startup", "from_build": prev, "from_version": prev.split("+")[0], "to_build": build},
            )
    atomic_write_json(path, {"build": build, "at": time.time()})
    return taken


START_ANYWAY = "KIBOTO_START_WITHOUT_SNAPSHOT"


def refuse_without_snapshot(err: BaseException) -> None:
    """A new build whose safety snapshot failed (a full disk, say) stops before it migrates any
    database, as the in-app updater does, so the previous image still runs on this data. Setting
    KIBOTO_START_WITHOUT_SNAPSHOT=1 starts it anyway (NREL-19)."""
    if legacy_names.getenv(START_ANYWAY, "").strip().lower() in ("1", "true", "yes"):
        logger.error(
            "[Main] No snapshot of the data folder for the new build (%s); starting anyway (%s)", err, START_ANYWAY
        )
        return
    logger.critical(
        "[Main] Could not snapshot the data folder before this new version changes it (%s). Nothing was "
        "changed: free some space in the data folder and restart, go back to the previous image, or set "
        "%s=1 to start without a way back.",
        err,
        START_ANYWAY,
    )
    raise SystemExit(4) from err


def snapshot_root(data_dir: str) -> str:
    return os.path.join(data_dir, SNAPSHOT_SUBDIR)


def _unreadable(path: str) -> bool:
    """A file Kiboto can't read because it isn't Kiboto's: Samba keeps its password databases as root
    in samba/private, inside the data folder. Only without root (the web user, ADR 0006 step 9): as
    root every error still fails the snapshot."""
    return hasattr(os, "geteuid") and os.geteuid() != 0 and not os.access(path, os.R_OK)


def _skip_special_files(directory: str, names: list[str]) -> list[str]:
    """Sockets, FIFOs and device nodes can't be copied (e.g. Samba's msg.sock); they hold no data.
    Half-written files of an atomic save (.tmp-*, *.tmp) are skipped too: they vanish when the save
    renames them, which failed the first snapshot at start-up (CI smoke test, 11 Nov 2026)."""
    skip = []
    for n in names:
        if n.startswith(".tmp-") or n.endswith(".tmp"):
            skip.append(n)
            continue
        try:
            mode = os.lstat(os.path.join(directory, n)).st_mode
        except OSError:
            continue
        if stat.S_ISSOCK(mode) or stat.S_ISFIFO(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
            skip.append(n)
        elif _unreadable(os.path.join(directory, n)):
            skip.append(n)
            _LEFT_OUT.append(os.path.join(directory, n))
    return skip


_LEFT_OUT: list[str] = []  # files left out of the snapshot being taken because they aren't Kiboto's


def _copytree_settled(src: str, dst: str) -> None:
    """copytree that forgives a file which disappeared between listing and copying (it was replaced
    by an atomic save); any other error still fails the snapshot."""
    try:
        shutil.copytree(src, dst, symlinks=True, ignore=_skip_special_files)
    except shutil.Error as e:
        real = [err for err in e.args[0] if os.path.exists(err[0])]
        if real:
            raise shutil.Error(real) from e
        logger.info("[Snapshot] %s file(s) changed while being copied and were left out", len(e.args[0]))


def take_snapshot(
    data_dir: str,
    label: str = "",
    extra: dict[str, Any] | None = None,
    protect: str | None = None,
    root: str | None = None,
    keep: int = KEEP,
) -> str:
    """Copies the data folder's settings and databases into a new snapshot under `root`
    (pre-update snapshots by default) and keeps the newest `keep`."""
    root = root or snapshot_root(data_dir)
    safe_label = "".join(c if c.isalnum() or c in ".-_" else "_" for c in label)[:40]
    dest = os.path.join(root, time.strftime("%Y%m%d-%H%M%S") + (f"-{safe_label}" if safe_label else ""))
    os.makedirs(dest, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)

    files: list[str] = []
    _LEFT_OUT.clear()
    for name in sorted(os.listdir(data_dir)):
        src = os.path.join(data_dir, name)
        if os.path.islink(src) or not os.path.isfile(src) or not _wanted_file(name):
            continue
        if _unreadable(src):
            _LEFT_OUT.append(src)
            continue
        dst = os.path.join(dest, name)
        if name.endswith(".db"):
            _copy_db(src, dst)
        else:
            try:
                shutil.copy2(src, dst)
            except FileNotFoundError:
                continue  # replaced by an atomic save between listing and copying
        files.append(name)
    for name in INCLUDE_DIRS:
        src = os.path.join(data_dir, name)
        if os.path.isdir(src) and not os.path.islink(src):
            _copytree_settled(src, os.path.join(dest, name))
            files.append(name + "/")

    left_out = sorted(os.path.relpath(f, data_dir) for f in _LEFT_OUT)
    if left_out:
        # a restore leaves these in place, so nothing is lost by not copying them
        logger.info("[Snapshot] Left out %s file(s) that aren't Kiboto's: %s", len(left_out), ", ".join(left_out))
    manifest = {"created_at": time.time(), "label": label, "files": files, "left_out": left_out, **(extra or {})}
    atomic_write_json(os.path.join(dest, MANIFEST), manifest, indent=2)
    _prune(root, protect, keep)
    logger.info("[Snapshot] Saved %s item(s) to %s", len(files), dest)
    return dest


def _prune(root: str, protect: str | None = None, keep_count: int = KEEP) -> None:
    keep = {os.path.basename(os.path.normpath(protect))} if protect else set()
    snaps = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    stable = [d for d in snaps if (read_json(os.path.join(root, d, MANIFEST), {}) or {}).get("stable")]
    if stable:
        keep.add(stable[-1])  # always one way back to the last Stable build (OPS-5)
    for old in [d for d in snaps if d not in keep][:-keep_count]:
        shutil.rmtree(os.path.join(root, old), ignore_errors=True)


def list_snapshots(data_dir: str) -> list[dict[str, Any]]:
    root = snapshot_root(data_dir)
    if not os.path.isdir(root):
        return []
    out = []
    for d in sorted(os.listdir(root), reverse=True):
        path = os.path.join(root, d)
        try:
            with open(os.path.join(path, MANIFEST), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        out.append({"id": d, "path": path, **meta})
    return out


def restore_snapshot(snapshot_dir: str, data_dir: str) -> list[str]:
    """Copies a snapshot back over data_dir. Run only while Kiboto is stopped."""
    with open(os.path.join(snapshot_dir, MANIFEST), encoding="utf-8") as f:
        files = json.load(f).get("files") or []
    for item in files:
        # the list is a file in the data folder: a name that leaves the folder is never followed
        name = item.rstrip("/") if isinstance(item, str) else ""
        if not name or os.path.isabs(name) or ".." in name.split("/"):
            raise ValueError(f"the snapshot lists {item!r}, which is not a file of the data folder")
    restored = []
    for item in files:
        src = os.path.join(snapshot_dir, item.rstrip("/"))
        dst = os.path.join(data_dir, item.rstrip("/"))
        if item.endswith("/"):
            if os.path.isdir(dst) and not os.path.islink(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst, symlinks=True)
        else:
            for suffix in ("-wal", "-shm"):
                if os.path.exists(dst + suffix):
                    os.remove(dst + suffix)
            tmp = dst + ".restore-tmp"
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)
        restored.append(item)
    logger.warning("[Snapshot] Restored %s item(s) from %s", len(restored), snapshot_dir)
    return restored


def main(argv: list[str]) -> int:
    """`take <data folder> <label> <extra as JSON>` prints the snapshot's folder; `restore <snapshot>
    <data folder>` puts one back. For the updater, which runs this as the data folder's owner."""
    import sys

    try:
        if argv[1:2] == ["take"] and len(argv) == 5:
            print(take_snapshot(argv[2], label=argv[3], extra=json.loads(argv[4])))
            return 0
        if argv[1:2] == ["restore"] and len(argv) == 4:
            restore_snapshot(argv[2], argv[3])
            return 0
    except (OSError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv))
