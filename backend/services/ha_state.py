"""High availability: the second NAS keeps a copy of the first one's people and settings (the
owner's decision of 19 Nov 2026: it is applied only when the second NAS takes over; until then
the second NAS keeps its own sign-ins and settings).

The copy is the same encrypted settings backup the Backup page makes (people with their password
fingerprints and two-step sign-in, settings, shares, apps' stacks, and the install's key that the
sealed parts need). The first NAS makes it when the second one asks, under a passphrase made for
that one copy; both travel over the sealed link (ha_link.py), the backup in pieces. The second NAS
keeps the backup as it came and the passphrase sealed with its own key. It asks once a night, and
when "Fetch now" is pressed."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import threading
import time
from typing import Any

from backend import __version__, secret_box
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json
from backend.services import ha_link
from backend.services.ha_link import LinkError

DIR = os.path.join(DATA_DIR, "ha")
COPY = "settings.bin"
INFO = "settings.json"
SERVED = "served.json"
PIECE = 1024 * 1024  # how much of the backup travels in one sealed message
MAX_BYTES = 256 * 1024 * 1024  # what a settings backup may be at most (as when one is uploaded)
OFFER_SECS = 900  # how long the first NAS keeps a backup it made for the second one to collect
FETCH_AT = "02:30"

_lock = threading.Lock()
_offers: dict[str, dict[str, Any]] = {}  # on the first NAS: backups waiting to be collected
_state: dict[str, Any] = {"fetching": False, "error": "", "ran": ""}


def make_archive(passphrase: str) -> bytes:
    """The encrypted settings backup of this box, as the Backup page makes it."""
    from backend.services.backup_engine import generate_backup_zip_stream

    stream = generate_backup_zip_stream(passphrase=passphrase)
    try:
        return stream.read()
    finally:
        stream.close()


# --- on the first NAS: what the second one may ask for ---------------------------------------------
def _expire(now: float) -> None:
    for offer_id in [i for i, o in _offers.items() if now > o["expires"]]:
        _drop(offer_id)


def _drop(offer_id: str) -> None:
    offer = _offers.pop(offer_id, None)
    if offer:
        try:
            os.remove(offer["path"])
        except OSError:
            logger.debug("[HA] %s was gone already", offer["path"], exc_info=True)


def _begin(_args: dict[str, Any]) -> dict[str, Any]:
    """Makes a settings backup for the second NAS and says how large it is and what opens it."""
    if ha_link.role() != "first":
        raise LinkError("not_first", "This NAS is not the first NAS of the pair.")
    now = time.time()
    with _lock:
        _expire(now)
        for other in list(_offers):  # one at a time: a new request replaces the one before
            _drop(other)
        passphrase = secrets.token_urlsafe(32)
        data = make_archive(passphrase)
        if len(data) > MAX_BYTES:
            raise LinkError("too_large", "The settings backup is too large to hand over.")
        os.makedirs(DIR, mode=0o700, exist_ok=True)
        offer_id = secrets.token_hex(8)
        path = os.path.join(DIR, f"offer-{offer_id}.bin")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        _offers[offer_id] = {"path": path, "size": len(data), "expires": now + OFFER_SECS}
    return {
        "id": offer_id,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "pass": passphrase,
        "made": now,
        "name": ha_link.my_name(),
        "version": __version__,
    }


def _piece(args: dict[str, Any]) -> dict[str, Any]:
    offer = _offers.get(str(args.get("id") or ""))
    number = args.get("n")
    if offer is None or not isinstance(number, int) or number < 0 or number * PIECE >= max(offer["size"], 1):
        raise LinkError("no_offer", "There is no such piece to collect.")
    with open(offer["path"], "rb") as f:
        f.seek(number * PIECE)
        return {"data": base64.b64encode(f.read(PIECE)).decode()}


def _end(args: dict[str, Any]) -> dict[str, Any]:
    """The second NAS has it all: the first one's copy of the backup goes, and the time is noted."""
    with _lock:
        _drop(str(args.get("id") or ""))
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    atomic_write_json(os.path.join(DIR, SERVED), {"at": time.time()})
    return {"ok": True}


ha_link.HANDLERS.update(settings_begin=_begin, settings_piece=_piece, settings_end=_end)


def served() -> float | None:
    """On the first NAS: when the second one last collected people and settings."""
    said = read_json(os.path.join(DIR, SERVED), {})
    return float(said["at"]) if isinstance(said, dict) and said.get("at") else None


# --- on the second NAS: asking, and keeping what came ----------------------------------------------
def info() -> dict[str, Any] | None:
    """The copy this box keeps: when it was made and fetched, from whom, how large. Never what opens it."""
    kept = read_json(os.path.join(DIR, INFO), {})
    if not isinstance(kept, dict) or not kept.get("sha256") or not os.path.isfile(os.path.join(DIR, COPY)):
        return None
    return {k: kept.get(k) for k in ("made", "fetched", "size", "name", "version")}


def passphrase() -> str:
    """What opens the kept copy; for the takeover only."""
    kept = read_json(os.path.join(DIR, INFO), {})
    return secret_box.unseal(kept["pass"]) if isinstance(kept, dict) and kept.get("pass") else ""


@json_locked(lambda *a, **k: os.path.join(DIR, INFO))
def reseal() -> int:
    """After the install's secret key was replaced: what opens the kept copy, sealed with the new one."""
    path = os.path.join(DIR, INFO)
    kept = read_json(path, {})
    if not isinstance(kept, dict) or not secret_box.is_sealed(str(kept.get("pass") or "")):
        return 0
    kept["pass"] = secret_box.seal(secret_box.unseal(kept["pass"]))
    atomic_write_json(path, kept)
    return 1


def fetch(send: ha_link.Sender | None = None) -> dict[str, Any]:
    """Asks the first NAS for its people and settings and keeps the copy. Raises LinkError."""
    if ha_link.role() != "second":
        raise LinkError("not_second", "Only the second NAS fetches the first one's people and settings.")
    ask = (lambda op, args=None: ha_link.call(op, args, send=send)) if send else ha_link.call
    begun = ask("settings_begin")
    size, want = int(begun.get("size") or 0), str(begun.get("sha256") or "")
    if not 0 < size <= MAX_BYTES or len(want) != 64 or not begun.get("pass"):
        raise LinkError("bad_copy", "The first NAS offered a copy that cannot be used.")
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    target = os.path.join(DIR, COPY)
    digest, got = hashlib.sha256(), 0
    fd = os.open(target + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            for number in range((size + PIECE - 1) // PIECE):
                piece = base64.b64decode(str(ask("settings_piece", {"id": begun["id"], "n": number}).get("data") or ""))
                got += len(piece)
                if not piece or got > size:
                    raise LinkError("bad_copy", "The copy did not arrive whole.")
                digest.update(piece)
                f.write(piece)
            f.flush()
            os.fsync(f.fileno())
        if got != size or digest.hexdigest() != want:
            raise LinkError("bad_copy", "The copy did not arrive whole.")
        os.replace(target + ".new", target)
    finally:
        if os.path.exists(target + ".new"):
            os.remove(target + ".new")
    kept = {
        "made": begun.get("made"),
        "fetched": time.time(),
        "size": size,
        "sha256": want,
        "name": str(begun.get("name") or "")[:64],
        "version": str(begun.get("version") or "")[:32],
        "pass": secret_box.seal(str(begun["pass"])),
    }
    atomic_write_json(os.path.join(DIR, INFO), kept)
    try:
        ask("settings_end", {"id": begun["id"]})
    except LinkError:
        logger.debug("[HA] the first NAS was not told that the copy arrived; it forgets its own in time", exc_info=True)
    logger.info("[HA] people and settings of %s fetched (%d bytes)", kept["name"], size)
    return info() or {}


def fetch_soon() -> bool:
    """Fetches in the background; False when a fetch is going already."""
    with _lock:
        if _state["fetching"]:
            return False
        _state.update(fetching=True, error="")

    def work() -> None:
        from backend.services import ha_folders

        try:
            fetch()
        except LinkError as e:
            _state["error"] = e.key
            logger.warning("[HA] people and settings were not fetched: %s", e)
        except (OSError, ValueError, KeyError, TypeError):
            _state["error"] = "failed"
            logger.warning("[HA] people and settings were not fetched", exc_info=True)
        try:
            ha_folders.fetch_all()  # then the chosen folders, one after the other
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("[HA] the folders were not fetched", exc_info=True)
        finally:
            _state["fetching"] = False

    threading.Thread(target=work, name="ha-fetch", daemon=True).start()
    return True


def run_due(now: float | None = None) -> bool:
    """Called every minute: on the second NAS, once a night at FETCH_AT."""
    now = time.time() if now is None else now
    t = time.localtime(now)
    day = time.strftime("%Y-%m-%d", t)
    if f"{t.tm_hour:02d}:{t.tm_min:02d}" != FETCH_AT or _state["ran"] == day or ha_link.role() != "second":
        return False
    _state["ran"] = day
    return fetch_soon()


def forget() -> None:
    """Unpaired: the copy of the other box's people and settings goes."""
    for name in (COPY, INFO, SERVED):
        try:
            os.remove(os.path.join(DIR, name))
        except FileNotFoundError:
            continue
        except OSError:
            logger.warning("[HA] %s could not be removed", name, exc_info=True)


ha_link.ON_UNPAIR.append(forget)


def view() -> dict[str, Any]:
    """What the screen adds to the link's status."""
    return {
        "copy": info(),
        "fetching": bool(_state["fetching"]),
        "fetch_error": _state["error"],
        "served": served(),
        "fetch_at": FETCH_AT,
    }
