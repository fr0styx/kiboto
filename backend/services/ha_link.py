"""Two Kiboto boxes that stand in for each other (high availability, the owner's decisions of
19 Nov 2026): the link between them.

One box is the first NAS, the one the family uses. The other is the second NAS: it keeps a copy
of chosen folders, people and settings, and takes over when its owner presses a button. This
module is the link only: pairing, and messages no one else on the network can read or forge.
What travels over it (settings, folders, the takeover) builds on `call` and `HANDLERS`.

The boxes may be on the home network without Tailscale, so the link brings its own encryption:

  - Pairing: the first NAS shows a pairing key (80 random bits, 10 minutes, one use). It is typed
    into the second NAS with the first one's address. Each side makes a fresh key pair (X25519)
    and proves with the pairing key that its public half is its own; someone in between who does
    not have the pairing key can neither read nor replace them. The key both sides then share
    never travels.
  - Afterwards every message is sealed with that key (AES-256-GCM), names its sender and
    receiver, carries the time, and is accepted once.

The address is a number address on the home network or on Tailscale (or a .ts.net name): Kiboto
does not look names up for this, so nothing can point the link somewhere else."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)  # gitleaks:allow (an import, not a key)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend import __version__, secret_box
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json

STATE_FILE = os.path.join(DATA_DIR, "ha.json")
CODE_SECONDS = 600
CODE_TRIES = 5
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 32 signs, none that look alike: 5 bits each
CODE_SIGNS = 16  # 80 bits
CLOCK_SLACK_SECS = 120  # a message older or newer than this is refused
PAIR_PATH = "/api/ha/peer/pair"
CALL_PATH = "/api/ha/peer/call"
TIMEOUT = 10.0
MAX_REPLY = 8 * 1024 * 1024
BAD_ADDRESS = "Use the other NAS's number address, like http://192.168.1.20:8082."
_TS4 = ipaddress.ip_network("100.64.0.0/10")
_TS6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")

_lock = threading.Lock()
_seen: dict[str, float] = {}  # message numbers accepted lately -> when
_last: dict[str, Any] = {"at": 0.0, "ok": None, "error": ""}  # the last contact with the other box

Sender = Callable[[str, dict[str, Any]], dict[str, Any]]


class LinkError(RuntimeError):
    """Something that cannot be done; `key` names the sentence for the screen."""

    def __init__(self, key: str, message: str):
        super().__init__(message)
        self.key = key


# --- what is kept -------------------------------------------------------------------------------
def _state() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    return data if isinstance(data, dict) else {}


@json_locked(lambda *a, **k: STATE_FILE)
def _change(change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    data = _state()
    change(data)
    atomic_write_json(STATE_FILE, data)
    return data


def box_id() -> str:
    """This box's own name on the link, made once."""
    have = _state().get("box_id")
    if isinstance(have, str) and len(have) == 16:
        return have
    made = secrets.token_hex(8)
    return _change(lambda d: d.setdefault("box_id", made))["box_id"]


def peer() -> dict[str, Any] | None:
    found = _state().get("peer")
    return found if isinstance(found, dict) and found.get("id") and found.get("key") else None


def role() -> str:
    """This box's part: "first", "second", or nothing when it is not paired."""
    state = _state()
    return str(state.get("role") or "") if peer() is not None else ""


def my_name() -> str:
    from backend.services import fleet

    return fleet.my_name()


def audit(event: str, detail: str, actor: str) -> None:
    from backend.users_db import log_security_event

    log_security_event(f"ha.{event}", "success", actor_username=actor or None, details={"detail": detail})


# --- the address ----------------------------------------------------------------------------------
def clean_address(address: str) -> str:
    """http(s)://<number address>[:port] on the home network or on Tailscale, or a .ts.net name."""
    address = (address or "").strip().rstrip("/")
    try:
        parts = urlsplit(address)
        host = (parts.hostname or "").lower()
        plain = parts.scheme in ("http", "https") and parts.path in ("", "/") and not parts.query
        plain = plain and not parts.username and not parts.password and (parts.port is None or parts.port > 0)
    except ValueError:
        host, plain = "", False
    if not host or not plain:
        raise LinkError("bad_address", BAD_ADDRESS)
    if host.endswith(".ts.net"):
        return address
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise LinkError("bad_address", BAD_ADDRESS) from None
    home = ip.is_private and not ip.is_loopback and not ip.is_unspecified and not ip.is_multicast
    if not (home or ip in _TS4 or ip in _TS6):
        raise LinkError("not_home", "The other NAS has to be on your home network or on Tailscale.")
    return address


# --- keys -----------------------------------------------------------------------------------------
def new_code_text() -> str:
    signs = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_SIGNS))
    return "-".join(signs[i : i + 4] for i in range(0, CODE_SIGNS, 4))


def _norm(code: str) -> str:
    return "".join(c for c in (code or "").upper() if c in CODE_ALPHABET)


def _hkdf(secret: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(secret)


def _code_key(code: str) -> bytes:
    return _hkdf(_norm(code).encode(), b"kiboto-ha-pairing-v1", b"pairing key")


def _proof(code_key: bytes, *parts: str) -> str:
    return hmac.new(code_key, "|".join(parts).encode(), hashlib.sha256).hexdigest()


def _public(private: X25519PrivateKey) -> str:
    raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def _link_key(private: X25519PrivateKey, their_public: str, code_key: bytes, first_id: str, second_id: str) -> bytes:
    try:
        theirs = X25519PublicKey.from_public_bytes(base64.b64decode(their_public, validate=True))
        shared = private.exchange(theirs)
    except (ValueError, TypeError) as e:
        raise LinkError("bad_pairing", "The other NAS sent a key that cannot be used.") from e
    return _hkdf(shared, code_key, f"kiboto-ha-link-v1|{first_id}|{second_id}".encode())


def _keep_peer(as_role: str, their_id: str, name: str, address: str, key: bytes) -> None:
    sealed = secret_box.seal(base64.b64encode(key).decode())
    found = {"id": their_id, "name": name[:64], "address": address, "key": sealed, "paired_at": time.time()}

    def change(data: dict[str, Any]) -> None:
        data.update(role=as_role, peer=found)
        data.pop("code", None)

    _change(change)
    _last.update(at=time.time(), ok=True, error="")


def _key_of(found: dict[str, Any]) -> bytes:
    return base64.b64decode(secret_box.unseal(found["key"]))


# --- sealed messages ------------------------------------------------------------------------------
def seal(key: bytes, sender: str, receiver: str, message: Any, reply_to: str = "") -> dict[str, str]:
    """A message only the two boxes can read: who it is from, a number used once, and the sealed text."""
    nonce = secrets.token_bytes(12)
    plain = json.dumps({"t": time.time(), "m": message}, separators=(",", ":")).encode()
    aad = f"kiboto-ha-v1|{sender}|{receiver}|{reply_to}".encode()
    sealed = AESGCM(key).encrypt(nonce, plain, aad)
    return {"from": sender, "n": base64.b64encode(nonce).decode(), "c": base64.b64encode(sealed).decode()}


def unseal(key: bytes, sender: str, receiver: str, envelope: dict[str, Any], reply_to: str = "") -> Any:
    """What a sealed message says. Refused: made with another key, changed on the way, meant for
    someone else, too old or from the future, or seen before."""
    try:
        nonce = base64.b64decode(str(envelope.get("n") or ""), validate=True)
        sealed = base64.b64decode(str(envelope.get("c") or ""), validate=True)
        aad = f"kiboto-ha-v1|{sender}|{receiver}|{reply_to}".encode()
        said = json.loads(AESGCM(key).decrypt(nonce, sealed, aad))
    except (InvalidTag, ValueError, TypeError) as e:
        raise LinkError("bad_message", "A message from the other NAS could not be read.") from e
    now = time.time()
    if not isinstance(said, dict) or abs(now - float(said.get("t") or 0)) > CLOCK_SLACK_SECS:
        raise LinkError("clock", "The two NAS boxes do not agree on the time.")
    mark = f"{sender}|{envelope.get('n')}"
    with _lock:
        for old in [m for m, at in _seen.items() if now - at > 2 * CLOCK_SLACK_SECS]:
            del _seen[old]
        if mark in _seen:
            raise LinkError("bad_message", "A message from the other NAS came twice.")
        _seen[mark] = now
    return said.get("m")


# --- pairing --------------------------------------------------------------------------------------
def new_code(actor: str = "") -> dict[str, Any]:
    """On the first NAS: a pairing key to type into the second one. It is shown once."""
    if peer() is not None:
        raise LinkError("paired", "This NAS is paired already. Unpair it first.")
    code = new_code_text()
    kept = {"sealed": secret_box.seal(_norm(code)), "expires": time.time() + CODE_SECONDS, "tries": 0}
    _change(lambda d: d.update(code=kept))
    audit("code", "a pairing key was made", actor)
    return {"code": code, "valid_seconds": CODE_SECONDS}


def accept_pairing(their_id: str, name: str, address: str, their_public: str, proof: str) -> dict[str, Any]:
    """On the first NAS: the second one asks to pair. It must prove it has the pairing key; the
    answer proves the same to it. A wrong proof counts as a try, and the key is gone after five."""
    with _lock:
        kept = _state().get("code") or {}
        if peer() is not None or not kept.get("sealed") or time.time() > float(kept.get("expires") or 0):
            raise LinkError("no_code", "There is no pairing key waiting on this NAS.")
        address = clean_address(address)
        mine = box_id()
        code_key = _code_key(secret_box.unseal(kept["sealed"]))
        if not hmac.compare_digest(_proof(code_key, "second", their_id, their_public), str(proof)):
            tries = int(kept.get("tries") or 0) + 1

            def count(data: dict[str, Any]) -> None:
                if tries >= CODE_TRIES:
                    data.pop("code", None)
                else:
                    data["code"] = {**kept, "tries": tries}

            _change(count)
            raise LinkError("bad_pairing", "The pairing key is not right.")
        private = X25519PrivateKey.generate()
        key = _link_key(private, their_public, code_key, mine, their_id)
        _keep_peer("first", their_id, name, address, key)
    audit("paired", f"paired with {name}: this is the first NAS", "")
    public = _public(private)
    return {
        "box_id": mine,
        "name": my_name(),
        "public": public,
        "proof": _proof(code_key, "first", mine, public, their_id, their_public),
    }


THEIR_REASONS = ("no_code", "bad_pairing", "paired", "not_paired", "bad_message", "clock")


def _their_reason(e: urllib.error.HTTPError) -> str:
    """Why the other box refused, when it gave a reason this box has words for; else "refused"."""
    try:
        said = json.loads(e.read(4096))
    except (OSError, ValueError):
        return "refused"
    key = str(said.get("error") or "") if isinstance(said, dict) else ""
    return key[3:] if key.startswith("ha_") and key[3:] in THEIR_REASONS else "refused"


def _post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    """One request to the other box, no redirects followed, a bounded answer."""

    class _Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a: Any, **k: Any) -> None:
            return None

    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.build_opener(_Stay).open(req, timeout=TIMEOUT) as r:  # noqa: S310 (an address clean_address let through)
            said = json.loads(r.read(MAX_REPLY + 1)[:MAX_REPLY])
    except urllib.error.HTTPError as e:
        raise LinkError(_their_reason(e), f"The other NAS refused ({e.code}).") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise LinkError("unreachable", "The other NAS did not answer.") from e
    if not isinstance(said, dict):
        raise LinkError("refused", "The other NAS answered with something else.")
    return said


def pair_with(address: str, code: str, my_address: str, actor: str = "", send: Sender = _post) -> dict[str, Any]:
    """On the second NAS: pairs with the first one at `address`, using the pairing key shown there.
    `my_address` is where the first NAS reaches this one."""
    if peer() is not None:
        raise LinkError("paired", "This NAS is paired already. Unpair it first.")
    address, my_address = clean_address(address), clean_address(my_address)
    if len(_norm(code)) != CODE_SIGNS:
        raise LinkError("bad_pairing", "The pairing key is not right.")
    mine = box_id()
    code_key = _code_key(code)
    private = X25519PrivateKey.generate()
    public = _public(private)
    asked = {
        "box_id": mine,
        "name": my_name(),
        "address": my_address,
        "public": public,
        "proof": _proof(code_key, "second", mine, public),
    }
    said = send(address + PAIR_PATH, asked)
    their_id, their_public = str(said.get("box_id") or ""), str(said.get("public") or "")
    want = _proof(code_key, "first", their_id, their_public, mine, public)
    if len(their_id) != 16 or their_id == mine or not hmac.compare_digest(want, str(said.get("proof") or "")):
        raise LinkError("bad_pairing", "The other NAS could not show that it has the pairing key.")
    key = _link_key(private, their_public, code_key, their_id, mine)
    _keep_peer("second", their_id, str(said.get("name") or ""), address, key)
    audit("paired", f"paired with {said.get('name')}: this is the second NAS", actor)
    return status()


# --- talking --------------------------------------------------------------------------------------
def _hello(_args: dict[str, Any]) -> dict[str, Any]:
    return {"name": my_name(), "version": __version__, "role": role(), "time": time.time()}


def _forget_me(_args: dict[str, Any]) -> dict[str, Any]:
    unpair(tell=False)
    return {"ok": True}


# what the other box may ask for; later parts of high availability add theirs
HANDLERS: dict[str, Callable[[dict[str, Any]], Any]] = {"hello": _hello, "unpair": _forget_me}


def call(op: str, args: dict[str, Any] | None = None, send: Sender = _post) -> Any:
    """Asks the other box for something, sealed both ways."""
    found = peer()
    if found is None:
        raise LinkError("not_paired", "This NAS is not paired with another one.")
    key, mine = _key_of(found), box_id()
    envelope = seal(key, mine, found["id"], {"op": op, "args": args or {}})
    try:
        said = send(found["address"] + CALL_PATH, envelope)
        answer = unseal(key, found["id"], mine, said, reply_to=envelope["n"])
    except LinkError as e:
        _last.update(at=time.time(), ok=False, error=e.key)
        raise
    _last.update(at=time.time(), ok=True, error="")
    if isinstance(answer, dict) and answer.get("error"):
        raise LinkError("refused", str(answer["error"]))
    return answer


def handle_call(envelope: dict[str, Any]) -> dict[str, str]:
    """The other box asked for something: the sealed answer. Raises LinkError for anyone else."""
    found = peer()
    if found is None or not hmac.compare_digest(str(envelope.get("from") or ""), found["id"]):
        raise LinkError("not_paired", "Not the paired NAS.")
    key, mine = _key_of(found), box_id()
    asked = unseal(key, found["id"], mine, envelope)
    said = asked if isinstance(asked, dict) else {}
    handler = HANDLERS.get(str(said.get("op") or ""))
    raw = said.get("args")
    args: dict[str, Any] = raw if isinstance(raw, dict) else {}
    _last.update(at=time.time(), ok=True, error="")
    if handler is None:
        answer: Any = {"error": "This NAS does not know that request."}
    else:
        try:
            answer = handler(args)
        except LinkError as e:
            answer = {"error": str(e)}
    return seal(key, mine, found["id"], answer, reply_to=str(envelope.get("n") or ""))


def unpair(actor: str = "", tell: bool = True, send: Sender = _post) -> dict[str, Any]:
    """Forgets the other box and tells it, when it can be reached, to forget this one."""
    found = peer()
    if found is not None and tell:
        try:
            call("unpair", send=send)
        except LinkError:
            logger.info(
                "[HA] the other NAS could not be told about the unpairing; it keeps its side until unpaired there"
            )

    def change(data: dict[str, Any]) -> None:
        for name in ("peer", "role", "code"):
            data.pop(name, None)

    _change(change)
    _last.update(at=0.0, ok=None, error="")
    if found is not None:
        audit("unpaired", f"unpaired from {found.get('name')}", actor)
    return status()


def check(send: Sender = _post) -> dict[str, Any]:
    """Asks the other box whether it is there; the status afterwards, with what it said."""
    try:
        said = call("hello", send=send)
    except LinkError:
        return status()
    if isinstance(said, dict):
        _last["said"] = {k: said.get(k) for k in ("name", "version", "role")}
    return status()


def status() -> dict[str, Any]:
    """What the screen shows: this box's part, the other box, and how the last contact went."""
    state, found = _state(), peer()
    waiting = state.get("code") or {}
    out: dict[str, Any] = {
        "role": role(),
        "name": my_name(),
        "code_waiting": bool(waiting.get("sealed")) and time.time() < float(waiting.get("expires") or 0),
        "peer": None,
    }
    if found is not None:
        out["peer"] = {
            "name": found.get("name") or "",
            "address": found.get("address") or "",
            "paired_at": found.get("paired_at"),
            "last_contact": _last["at"] or None,
            "reachable": _last["ok"],
            "error": _last["error"],
            "said": _last.get("said"),
        }
    return out
