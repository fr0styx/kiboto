"""High availability: the second NAS keeps a copy of chosen shared folders of the first one (the
owner's decisions of 19 Nov 2026: fetched every night and on "Fetch now"; they land in a shared
folder of the same name; a file deleted on the first NAS is kept 30 days on the second).

Everything travels over the sealed link (ha_link.py): the first NAS lists a folder's files, the
second fetches the ones that are new or changed, in pieces. The second NAS is careful with what is
its own: it only replaces or puts away files it fetched itself and that nobody changed since. A
file of its own under the same name is left alone and counted. A file that is gone on the first
NAS moves to the hidden folder `.kiboto-removed/<day>` inside the share and goes after 30 days.

Links are not followed and not copied; only ordinary files and the folders that hold them."""

from __future__ import annotations

import base64
import itertools
import json
import os
import secrets
import shutil
import stat
import threading
import time
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json
from backend.services import ha_link
from backend.services.ha_link import LinkError

DIR = os.path.join(DATA_DIR, "ha")
STATE = "folders.json"
REMOVED = ".kiboto-removed"
PART = ".kiboto-fetching"
KEEP_REMOVED_DAYS = 30
PIECE = 4 * 1024 * 1024  # how much of a file travels in one sealed message
LINES = 2000  # how many files one piece of a folder's list names
MAX_FILES = 1_000_000  # per folder
MAX_FOLDERS = 20
ROOM_KEPT = 64 * 1024 * 1024
OFFER_SECS = 6 * 3600
ERRORS_KEPT = 20

_lock = threading.Lock()
_offers: dict[str, dict[str, Any]] = {}  # on the first NAS: lists waiting to be collected
_state: dict[str, Any] = {"fetching": False}


# --- shared folders on this box ----------------------------------------------------------------------
def shares() -> dict[str, str]:
    """This box's shared folders: name -> path."""
    from backend.hardware.pal_storage import get_storage_platform

    try:
        found = get_storage_platform().list_shares()
    except (OSError, RuntimeError, ValueError):
        logger.debug("[HA] the shared folders could not be read", exc_info=True)
        return {}
    return {s.name: s.mountpoint for s in found if s.name and s.mountpoint and os.path.isdir(s.mountpoint)}


def make_share(name: str) -> str:
    """Makes a shared folder of this name on this box, private until its people are set; its path.
    LinkError where this system's shared folders are not Kiboto's to make."""
    from backend.hardware.pal_storage import get_storage_platform

    plat = get_storage_platform()
    if not plat.get_capabilities().can_manage_shares:
        raise LinkError("make_folder", f"Make a shared folder named {name} on this NAS first.")
    try:
        plat.create_share(name, "", comment="Copy of the first NAS's folder", security="private")
    except (OSError, RuntimeError, ValueError) as e:
        raise LinkError("make_folder", f"The shared folder {name} could not be made: {e}") from e
    path = shares().get(name)
    if not path:
        raise LinkError("make_folder", f"The shared folder {name} could not be made.")
    return path


def _inside(root: str, rel: str) -> str:
    """root/rel for a path the other box named; LinkError for one that would leave the folder."""
    parts = rel.split("/")
    if (
        not rel
        or rel.startswith("/")
        or any(p in ("", ".", "..") for p in parts)
        or parts[0] == REMOVED
        or "\x00" in rel
    ):
        raise LinkError("bad_path", "The other NAS named a file outside the folder.")
    return os.path.join(root, *parts)


# --- on the first NAS: what the second one may ask for -----------------------------------------------
def _first() -> None:
    if ha_link.role() != "first":
        raise LinkError("not_first", "This NAS is not the first NAS of the pair.")


def _list(_args: dict[str, Any]) -> dict[str, Any]:
    _first()
    return {"folders": sorted(shares())}


def _walk(root: str) -> Any:
    """Each ordinary file under root: (path from root, size, changed at, mode). No links, no hidden removal folder."""
    for at, dirs, names in os.walk(root):
        dirs[:] = sorted(
            d for d in dirs if not os.path.islink(os.path.join(at, d)) and not (at == root and d == REMOVED)
        )
        for name in sorted(names):
            path = os.path.join(at, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode) and not name.endswith(PART):
                yield (
                    os.path.relpath(path, root).replace(os.sep, "/"),
                    st.st_size,
                    st.st_mtime_ns,
                    stat.S_IMODE(st.st_mode),
                )


def _tree_begin(args: dict[str, Any]) -> dict[str, Any]:
    """Lists a shared folder's files into a file of this box, to be collected in pieces."""
    _first()
    root = shares().get(str(args.get("name") or ""))
    if not root:
        raise LinkError("no_folder", "The first NAS has no such shared folder.")
    now = time.time()
    with _lock:
        for old in [i for i, o in _offers.items() if now > o["expires"]]:
            _drop(old)
        os.makedirs(DIR, mode=0o700, exist_ok=True)
        offer_id = secrets.token_hex(8)
        path = os.path.join(DIR, f"tree-{offer_id}.jsonl")
        marks, count, total = [0], 0, 0
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for entry in _walk(root):
                if count >= MAX_FILES:
                    _offers[offer_id] = {"path": path, "expires": 0}
                    _drop(offer_id)
                    raise LinkError("too_many", "This folder has more files than can be kept in step.")
                f.write(json.dumps(entry, separators=(",", ":")) + "\n")
                count += 1
                total += entry[1]
                if count % LINES == 0:
                    marks.append(f.tell())
        _offers[offer_id] = {"path": path, "marks": marks, "count": count, "expires": now + OFFER_SECS}
    return {"id": offer_id, "files": count, "bytes": total, "pieces": (count + LINES - 1) // LINES}


def _drop(offer_id: str) -> None:
    offer = _offers.pop(offer_id, None)
    if offer:
        try:
            os.remove(offer["path"])
        except OSError:
            logger.debug("[HA] %s was gone already", offer["path"], exc_info=True)


def _tree_piece(args: dict[str, Any]) -> dict[str, Any]:
    offer = _offers.get(str(args.get("id") or ""))
    number = args.get("n")
    if offer is None or not isinstance(number, int) or not 0 <= number < len(offer["marks"]):
        raise LinkError("no_offer", "There is no such piece to collect.")
    with open(offer["path"], encoding="utf-8") as f:
        f.seek(offer["marks"][number])
        lines = [json.loads(line) for line in itertools.islice(f, LINES)]
    return {"entries": lines}


def _tree_end(args: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        _drop(str(args.get("id") or ""))
    return {"ok": True}


def _file_piece(args: dict[str, Any]) -> dict[str, Any]:
    """A piece of one file of a shared folder, and whether it was the last."""
    _first()
    root = shares().get(str(args.get("name") or ""))
    offset = args.get("offset")
    if not root or not isinstance(offset, int) or offset < 0:
        raise LinkError("no_folder", "The first NAS has no such shared folder.")
    path = _inside(root, str(args.get("rel") or ""))
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(root) + os.sep):
        raise LinkError("bad_path", "The other NAS named a file outside the folder.")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        raise LinkError("gone", "The file is no longer there.") from e
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise LinkError("gone", "The file is no longer an ordinary file.")
        data = os.pread(fd, PIECE, offset)
    finally:
        os.close(fd)
    return {"data": base64.b64encode(data).decode(), "eof": offset + len(data) >= st.st_size, "size": st.st_size}


ha_link.HANDLERS.update(
    folders_list=_list, tree_begin=_tree_begin, tree_piece=_tree_piece, tree_end=_tree_end, file_piece=_file_piece
)


# --- on the second NAS: which folders, and how the last fetch went -----------------------------------
def _kept() -> dict[str, Any]:
    data = read_json(os.path.join(DIR, STATE), {})
    data = data if isinstance(data, dict) else {}
    chosen = [n for n in data.get("chosen") or [] if isinstance(n, str)]
    return {"chosen": chosen, "last": data.get("last") if isinstance(data.get("last"), dict) else {}}


@json_locked(lambda *a, **k: os.path.join(DIR, STATE))
def _keep(chosen: list[str] | None = None, name: str = "", result: dict[str, Any] | None = None) -> None:
    data = _kept()
    if chosen is not None:
        data["chosen"] = chosen
        data["last"] = {n: r for n, r in data["last"].items() if n in chosen}
    if name and result is not None:
        data["last"][name] = result
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    atomic_write_json(os.path.join(DIR, STATE), data)


def chosen() -> list[str]:
    return _kept()["chosen"]


def choose(names: list[str], send: ha_link.Sender | None = None) -> list[str]:
    """Sets the folders the second NAS keeps: each must be a shared folder of the first NAS."""
    if ha_link.role() != "second":
        raise LinkError("not_second", "Only the second NAS fetches the first one's folders.")
    wanted = sorted({str(n) for n in names})
    if len(wanted) > MAX_FOLDERS:
        raise LinkError("too_many_folders", f"At most {MAX_FOLDERS} folders can be kept in step.")
    there = set(available(send)) if wanted else set()
    missing = [n for n in wanted if n not in there]
    if missing:
        raise LinkError("no_folder", f"The first NAS has no shared folder named {missing[0]}.")
    _keep(chosen=wanted)
    return wanted


def available(send: ha_link.Sender | None = None) -> list[str]:
    """The first NAS's shared folders, asked now."""
    said = ha_link.call("folders_list", send=send) if send else ha_link.call("folders_list")
    return [str(n) for n in (said or {}).get("folders") or []]


# --- on the second NAS: fetching one folder -----------------------------------------------------------
def _manifest(name: str) -> str:
    return os.path.join(DIR, "fetched-" + "".join(c if c.isalnum() or c in "-_" else "_" for c in name) + ".jsonl")


def _fetched_before(name: str) -> dict[str, tuple[int, int]]:
    """What this box fetched into the folder last time: path -> (size, changed at)."""
    out: dict[str, tuple[int, int]] = {}
    try:
        with open(_manifest(name), encoding="utf-8") as f:
            for line in f:
                rel, size, mtime = json.loads(line)
                out[rel] = (int(size), int(mtime))
    except (OSError, ValueError):
        return out
    return out


def _fetch_file(
    ask: Any, name: str, rel: str, size: int, mtime_ns: int, mode: int, local: str, like: os.stat_result
) -> None:
    """Fetches one file beside its place and puts it there when it arrived whole."""
    os.makedirs(os.path.dirname(local), exist_ok=True)
    part = local + PART
    got = 0
    try:
        with open(part, "wb") as f:
            while True:
                said = ask("file_piece", {"name": name, "rel": rel, "offset": got})
                data = base64.b64decode(str(said.get("data") or ""))
                f.write(data)
                got += len(data)
                if said.get("eof") or not data:
                    break
                if got > size:
                    raise LinkError("changed", "The file changed while it was fetched.")
            f.flush()
            os.fsync(f.fileno())
        if got != size:
            raise LinkError("changed", "The file changed while it was fetched.")
        os.chmod(part, (mode & 0o777) or 0o600)  # no mode told: the owner's alone, not everyone's
        if os.geteuid() == 0:
            os.chown(part, like.st_uid, like.st_gid)
        os.utime(part, ns=(mtime_ns, mtime_ns))
        os.replace(part, local)
    finally:
        if os.path.lexists(part):
            os.remove(part)


def _put_away(root: str, rel: str, day: str) -> None:
    """A file that is gone on the first NAS: kept in the hidden folder for a while."""
    target = os.path.join(root, REMOVED, day, *rel.split("/"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    os.replace(os.path.join(root, *rel.split("/")), target)


def prune_removed(root: str, now: float | None = None) -> int:
    """Removes what was put away more than KEEP_REMOVED_DAYS ago; returns how many days' folders went."""
    now = time.time() if now is None else now
    hidden, gone = os.path.join(root, REMOVED), 0
    try:
        days = sorted(os.listdir(hidden))
    except OSError:
        return 0
    for day in days:
        try:
            put = time.mktime(time.strptime(day, "%Y-%m-%d"))
        except ValueError:
            continue
        if now - put > KEEP_REMOVED_DAYS * 86400:
            shutil.rmtree(os.path.join(hidden, day), ignore_errors=True)
            gone += 1
    return gone


def fetch_folder(name: str, send: ha_link.Sender | None = None, now: float | None = None) -> dict[str, Any]:
    """Brings this box's copy of one folder in step with the first NAS. Returns how it went."""
    now = time.time() if now is None else now
    ask = (lambda op, args=None: ha_link.call(op, args, send=send)) if send else ha_link.call
    result: dict[str, Any] = {
        "at": now,
        "fetched": 0,
        "bytes": 0,
        "same": 0,
        "kept_yours": 0,
        "removed": 0,
        "errors": [],
        "why": "",
    }
    root = shares().get(name) or make_share(name)
    like = os.stat(root)
    before = _fetched_before(name)
    begun = ask("tree_begin", {"name": name})
    seen: set[str] = set()
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    try:
        with open(_manifest(name) + ".new", "w", encoding="utf-8") as record:
            for number in range(int(begun.get("pieces") or 0)):
                for rel, size, mtime_ns, mode in (
                    ask("tree_piece", {"id": begun["id"], "n": number}).get("entries") or []
                ):
                    seen.add(rel)
                    if result["why"]:
                        if rel in before:  # not reached this time: still known as fetched
                            record.write(json.dumps([rel, *before[rel]]) + "\n")
                        continue
                    try:
                        _one(
                            ask, name, root, like, before, record, result, str(rel), int(size), int(mtime_ns), int(mode)
                        )
                    except LinkError as e:
                        if e.key in ("unreachable", "not_paired", "bad_message", "clock"):
                            raise
                        _note(result, rel, str(e))
                    except OSError as e:
                        _note(result, rel, e.strerror or str(e))
            day = time.strftime("%Y-%m-%d", time.localtime(now))
            for rel, was in before.items():
                if rel in seen:
                    continue
                local = os.path.join(root, *rel.split("/"))
                try:
                    st = os.lstat(local)
                    if stat.S_ISREG(st.st_mode) and (st.st_size, st.st_mtime_ns) == was:
                        _put_away(root, rel, day)
                        result["removed"] += 1
                except FileNotFoundError:
                    continue
                except OSError as e:
                    _note(result, rel, e.strerror or str(e))
        os.replace(_manifest(name) + ".new", _manifest(name))
    finally:
        if os.path.exists(_manifest(name) + ".new"):
            os.remove(_manifest(name) + ".new")
        try:
            ask("tree_end", {"id": begun["id"]})
        except LinkError:
            logger.debug("[HA] the first NAS was not told that the list was read", exc_info=True)
    prune_removed(root, now)
    result["ended"] = time.time()
    return result


def _note(result: dict[str, Any], rel: str, why: str) -> None:
    if len(result["errors"]) < ERRORS_KEPT:
        result["errors"].append({"file": rel, "why": why})


def _one(
    ask: Any,
    name: str,
    root: str,
    like: os.stat_result,
    before: dict[str, tuple[int, int]],
    record: Any,
    result: dict[str, Any],
    rel: str,
    size: int,
    mtime_ns: int,
    mode: int,
) -> None:
    """One file of the first NAS's list: fetched, already the same, or left because it is this box's own."""
    local = _inside(root, rel)
    try:
        st: os.stat_result | None = os.lstat(local)
    except FileNotFoundError:
        st = None
    was = before.get(rel)
    if st is not None:
        mine = (st.st_size, st.st_mtime_ns)
        if stat.S_ISREG(st.st_mode) and mine == (size, mtime_ns):
            result["same"] += 1
            record.write(json.dumps([rel, size, mtime_ns]) + "\n")
            return
        if not stat.S_ISREG(st.st_mode) or was is None or mine != was:
            # a file of this box's own, or one someone changed here since it was fetched: left alone
            result["kept_yours"] += 1
            if was is not None:
                record.write(json.dumps([rel, *was]) + "\n")
            return
    if shutil.disk_usage(root).free < size + ROOM_KEPT:
        result["why"] = "full"
        if was is not None:
            record.write(json.dumps([rel, *was]) + "\n")
        return
    _fetch_file(ask, name, rel, size, mtime_ns, mode, local, like)
    result["fetched"] += 1
    result["bytes"] += size
    record.write(json.dumps([rel, size, mtime_ns]) + "\n")


def fetch_all(send: ha_link.Sender | None = None) -> dict[str, dict[str, Any]]:
    """Every chosen folder, one after the other; each one's result is kept for the screen."""
    out: dict[str, dict[str, Any]] = {}
    if ha_link.role() != "second":
        return out
    for name in chosen():
        try:
            result = fetch_folder(name, send=send)
        except LinkError as e:
            result = {
                "at": time.time(),
                "why": e.key,
                "errors": [],
                "fetched": 0,
                "bytes": 0,
                "same": 0,
                "kept_yours": 0,
                "removed": 0,
            }
            logger.warning("[HA] the folder %s was not fetched: %s", name, e)
        except OSError as e:
            result = {
                "at": time.time(),
                "why": "failed",
                "errors": [{"file": "", "why": e.strerror or str(e)}],
                "fetched": 0,
                "bytes": 0,
                "same": 0,
                "kept_yours": 0,
                "removed": 0,
            }
            logger.warning("[HA] the folder %s was not fetched", name, exc_info=True)
        _keep(name=name, result=result)
        out[name] = result
    return out


def forget() -> None:
    """Unpaired: which folders were chosen is forgotten. The copies themselves stay where they are."""
    try:
        names = os.listdir(DIR)
    except OSError:
        return
    for name in names:
        if name == STATE or name.startswith(("fetched-", "tree-")):
            try:
                os.remove(os.path.join(DIR, name))
            except OSError:
                logger.debug("[HA] %s could not be removed", name, exc_info=True)


ha_link.ON_UNPAIR.append(forget)


def view() -> dict[str, Any]:
    kept = _kept()
    return {"folders": kept["chosen"], "folders_last": kept["last"], "keep_removed_days": KEEP_REMOVED_DAYS}
