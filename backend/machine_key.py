"""The data key of a machine set up for Kiboto, sealed to that machine.

In a container the key that encrypts the AI chats and the AI search index comes from the
container's settings (KIBOTO_DATA_KEY), and without one they stay plain. On a machine of its own
Kiboto makes the key itself at the first start, so they are always encrypted there, and keeps it
sealed by systemd-creds: to the machine's security chip (TPM 2.0) together with a secret on the
system disk, or to that secret alone where there is no chip. A copy of the data folder cannot open
it, and neither can the system disk in another machine. The key is not bound to the firmware's
measurements, so a firmware update does not lock it.

The way back is a recovery key, six groups of four letters and digits, that the person writes
down: the data key is also kept wrapped under it. After a new board, or with a copy of the
settings on a system that was set up again, the recovery key opens the wrapped copy and the key is
sealed to the machine as it is now. Everything here lives outside the data folder, so no backup
and no snapshot of the data folder carries it.

`run` is the command runner; tests hand in their own."""

import base64
import os
import secrets
import subprocess
import time
from collections.abc import Callable
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from backend import runtime
from backend.config import logger
from backend.fsutil import atomic_write_json, read_json

DIR = "/etc/kiboto/keys"
CRED = "data-key.cred"  # the key, sealed to this machine
WRAPPED = "data-key.recovery"  # the same key under the recovery key
SHOWN = "recovery-key"  # the recovery key itself, until the person has written it down
STATE = "state.json"
NAME = "kiboto-data-key"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0, 1
GROUPS = 6
_AAD = b"kiboto:data-key:recovery:v1"
LOCKED = (
    "This machine could not open its data key: its security chip or its system disk is not the one "
    "the key was sealed to. Type the recovery key under Settings, Security."
)
NOT_THE_KEY = "That is not this machine's recovery key."
Run = Callable[..., tuple[int, str, str]]
ASK_AGAIN_AFTER = 60.0  # seconds before a chip that refused is asked again
_cache: dict[str, str] = {}
_refused_until = [0.0]


class MachineKeyError(RuntimeError):
    """The data key cannot be opened or sealed; the message is for the person."""


def run(cmd: list[str], feed: str | None = None, timeout: float = 60) -> tuple[int, str, str]:
    try:
        done = subprocess.run(  # noqa: S603
            cmd, input=feed, capture_output=True, text=True, timeout=timeout, check=False
        )
        return done.returncode, done.stdout or "", (done.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)


def _path(name: str) -> str:
    return os.path.join(DIR, name)


def active() -> bool:
    return runtime.managed_host()


def wanted() -> bool:
    """This machine has a data key of its own, sealed or waiting for the recovery key."""
    return active() and (os.path.exists(_path(CRED)) or os.path.exists(_path(WRAPPED)))


def has_chip(do: Run | None = None) -> bool:
    """A TPM 2.0 that systemd can use (chip, driver and libraries)."""
    do = do or run
    return do(["systemd-analyze", "has-tpm2"])[0] == 0


# --- the recovery key --------------------------------------------------------------------------
def new_recovery_key() -> str:
    """120 bits a person can copy by hand: no letters or digits that look alike."""
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(GROUPS))


def tidy(typed: str) -> str:
    """What was typed, as the key is written; '' when it cannot be a recovery key."""
    letters = "".join(ch for ch in (typed or "").upper() if ch.isalnum())
    if len(letters) != 4 * GROUPS or any(ch not in ALPHABET for ch in letters):
        return ""
    return "-".join(letters[i : i + 4] for i in range(0, len(letters), 4))


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _stretched(recovery_key: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(recovery_key.encode("ascii"))


def wrap(data_key: str, recovery_key: str) -> dict[str, Any]:
    salt, nonce = os.urandom(16), os.urandom(12)
    sealed = AESGCM(_stretched(recovery_key, salt)).encrypt(nonce, data_key.encode("ascii"), _AAD)
    return {"v": 1, "salt": _b64(salt), "nonce": _b64(nonce), "key": _b64(sealed)}


def unwrap(box: dict[str, Any], recovery_key: str) -> str:
    try:
        salt, nonce, sealed = (base64.b64decode(box[name]) for name in ("salt", "nonce", "key"))
        return AESGCM(_stretched(recovery_key, salt)).decrypt(nonce, sealed, _AAD).decode("ascii")
    except (InvalidTag, KeyError, TypeError, ValueError):
        raise MachineKeyError(NOT_THE_KEY) from None


# --- files only root reads ---------------------------------------------------------------------
def _write_secret(path: str, text: str) -> None:
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    tmp = path + ".part"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _state() -> dict[str, Any]:
    data = read_json(_path(STATE), {}) if os.path.exists(_path(STATE)) else {}
    return data if isinstance(data, dict) else {}


def _note(**changes: Any) -> None:
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    atomic_write_json(_path(STATE), {**_state(), **changes})


# --- sealing -----------------------------------------------------------------------------------
def _seal(data_key: str, do: Run) -> str:
    """Seals the key to this machine; says to what: 'chip' or 'disk'."""
    chip = has_chip(do)
    how = ["--with-key=host+tpm2", "--tpm2-pcrs="] if chip else ["--with-key=host"]
    part = _path(CRED) + ".part"
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    code, _, said = do(["systemd-creds", "encrypt", f"--name={NAME}", *how, "-", part], feed=data_key)
    if code != 0 or not os.path.exists(part):
        raise MachineKeyError(f"The data key could not be sealed to this machine: {said or 'systemd-creds failed'}")
    os.chmod(part, 0o600)
    os.replace(part, _path(CRED))
    _cache.clear()
    _refused_until[0] = 0.0
    _note(sealed_to="chip" if chip else "disk")
    return "chip" if chip else "disk"


def key_text(do: Run | None = None) -> str:
    """The data key, opened by this machine. Raises MachineKeyError with LOCKED when it cannot."""
    if "key" in _cache:
        return _cache["key"]
    if time.monotonic() < _refused_until[0]:
        raise MachineKeyError(LOCKED)  # asked a moment ago: the chip is not asked for every page
    do = do or run
    code, out, said = do(["systemd-creds", "decrypt", f"--name={NAME}", _path(CRED), "-"])
    key = out.strip()
    if code != 0 or len(key) < 32:
        _refused_until[0] = time.monotonic() + ASK_AGAIN_AFTER
        logger.error("[Key] The data key could not be opened: %s", (said or "no key came back").splitlines()[-1][:200])
        raise MachineKeyError(LOCKED)
    _cache["key"] = key
    return key


def ensure(do: Run | None = None) -> str:
    """At start. 'off' where Kiboto is a guest; 'sealed' when the key is there; 'made' at the first
    start (key made, sealed, recovery key waiting to be written down); 'locked' when only the
    wrapped copy is there and the recovery key has to be typed."""
    do = do or run
    if not active():
        return "off"
    if os.path.exists(_path(CRED)):
        return "sealed"
    if os.path.exists(_path(WRAPPED)):
        waiting = recovery_key_to_write_down()
        if not waiting:
            return "locked"
        unlock(waiting, do)  # a first start that was cut short between the two files
        return "sealed"
    data_key, recovery = secrets.token_hex(32), new_recovery_key()
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    atomic_write_json(_path(WRAPPED), wrap(data_key, recovery))
    os.chmod(_path(WRAPPED), 0o600)
    _write_secret(_path(SHOWN), recovery)
    where = _seal(data_key, do)
    _note(made_at=time.time(), written_down_at=None)
    logger.info("[Key] This machine has its data key, sealed to its %s", "security chip" if where == "chip" else "disk")
    return "made"


# --- for the page ------------------------------------------------------------------------------
def recovery_key_to_write_down() -> str:
    try:
        with open(_path(SHOWN), encoding="utf-8") as f:
            return tidy(f.read())
    except OSError:
        return ""


def written_down() -> bool:
    """The person has the recovery key: Kiboto forgets it."""
    if not os.path.exists(_path(SHOWN)):
        return False
    os.remove(_path(SHOWN))
    _note(written_down_at=time.time())
    return True


def unlock(typed: str, do: Run | None = None) -> str:
    """Opens the wrapped copy with the recovery key and seals the key to the machine as it is now."""
    do = do or run
    recovery = tidy(typed)
    box = read_json(_path(WRAPPED), None) if os.path.exists(_path(WRAPPED)) else None
    if not recovery or not isinstance(box, dict):
        raise MachineKeyError(NOT_THE_KEY)
    where = _seal(unwrap(box, recovery), do)
    logger.info("[Key] The data key was opened with the recovery key and sealed to this machine again")
    return where


def renew_recovery_key(do: Run | None = None) -> bool:
    """A new recovery key; the one before stops working. For a key that was lost or seen by someone."""
    data_key = key_text(do)
    recovery = new_recovery_key()
    atomic_write_json(_path(WRAPPED), wrap(data_key, recovery))
    os.chmod(_path(WRAPPED), 0o600)
    _write_secret(_path(SHOWN), recovery)
    _note(written_down_at=None)
    logger.info("[Key] A new recovery key was made; the one before no longer opens the data key")
    return True


def status(do: Run | None = None) -> dict[str, Any]:
    """What the page shows: never a key."""
    if not active():
        return {"managed": False}
    there = os.path.exists(_path(CRED))
    locked = not there and os.path.exists(_path(WRAPPED))
    if there:
        try:
            key_text(do)
        except MachineKeyError:
            locked = True
    saved = _state()
    return {
        "managed": True,
        "on": there or locked,
        "locked": locked,
        "sealed_to": saved.get("sealed_to") or "",
        "to_write_down": bool(recovery_key_to_write_down()),
        "written_down_at": saved.get("written_down_at"),
    }
