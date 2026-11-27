"""
Encryption at rest for the AI search index and the AI conversation history (AI-20).

With KIBOTO_DATA_KEY set in the container's environment (the Unraid template or the
compose file, never the data folder), rag_index.db and ai_conversations.db are SQLCipher
databases: AES-256 with a per-page HMAC. A copy of the data folder (a config backup, a
pre-update snapshot, the appdata share, a replicated or stolen cache drive) is then
unreadable without that key. Keep the key in a password manager: without it the chat
history is lost and the index has to be rebuilt.

- Without a key nothing changes: both files stay plain SQLite.
- First start with a key: existing plain files are converted to encrypted ones (the small
  chat database at startup, the index in the background while AI search waits).
- Key missing or wrong for an encrypted file: the file stays closed and the AI features
  that need it report why. Nothing is decrypted, overwritten or moved.

Both files always open through the SQLCipher module (which reads plain SQLite when no key
is given), so callers see one set of exception classes.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import logging
import os
import threading
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from backend import legacy_names

if TYPE_CHECKING:  # SQLCipher's module mirrors the stdlib API; type-check against the stdlib
    import sqlite3

    HAVE_SQLCIPHER: bool
else:
    try:
        from sqlcipher3 import dbapi2 as sqlite3

        HAVE_SQLCIPHER = True
    except ImportError:  # development machines without the wheel: plain SQLite only
        import sqlite3

        HAVE_SQLCIPHER = False

logger = logging.getLogger("Kiboto")

KEY_ENV = "KIBOTO_DATA_KEY"
KEY_FILE_ENV = "KIBOTO_DATA_KEY_FILE"  # a file holding the key, e.g. a Docker secret
CREDENTIAL_NAME = "kiboto-data-key"  # systemd: LoadCredentialEncrypted=kiboto-data-key:...
ENCRYPTED_NAMES = ("rag_index.db", "ai_conversations.db")
SQLITE_HEADER = b"SQLite format 3\x00"
MIN_KEY_CHARS = 16
_KDF_SALT = b"kiboto-data-key-v1"  # a database keyed with the salt of before is re-encrypted once (prepare)
_KDF_ROUNDS = 200_000

_ready: dict[str, threading.Event] = {}
_override = threading.local()  # key_for_this_thread
_failed: dict[str, str] = {}
_key_failed_at: dict[str, float] = {}  # when the key was not given: asked for again, not given up on
RETRY_KEY_AFTER = 60.0  # seconds; machine_key asks the security chip again after the same time
_now = time.monotonic
_ready_lock = threading.Lock()


class DataKeyError(RuntimeError):
    """An encrypted AI database cannot be opened (key missing, too short or wrong)."""


@contextlib.contextmanager
def key_for_this_thread(text: str) -> Iterator[None]:
    """While a backup of another install is checked, its AI databases open with that install's key
    (settings brought back from a pool copy, services/pool_copy.py). Only on this thread."""
    _override.text = text
    try:
        yield
    finally:
        _override.text = ""


def _key_text() -> str:
    """The key from KIBOTO_DATA_KEY, else the file KIBOTO_DATA_KEY_FILE names, else the systemd
    credential `kiboto-data-key` ($CREDENTIALS_DIRECTORY, e.g. sealed to the TPM with systemd-creds)."""
    if getattr(_override, "text", ""):
        return _override.text
    value = legacy_names.getenv(KEY_ENV, "")
    if value:
        return value
    path = legacy_names.getenv(KEY_FILE_ENV, "")
    if not path:
        path = _credential_path()
    if not path:
        return _machine_key()
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError as e:
        raise DataKeyError(f"Could not read the data key from {path}: {e}") from None


def _machine_key() -> str:
    """On a machine set up for Kiboto: the key that machine made and sealed to itself; '' elsewhere."""
    from backend import machine_key

    if not (HAVE_SQLCIPHER and machine_key.wanted()):
        return ""
    try:
        return machine_key.key_text()
    except machine_key.MachineKeyError as e:
        raise DataKeyError(str(e)) from None


def _own_key_wanted() -> bool:
    from backend import machine_key

    return HAVE_SQLCIPHER and machine_key.wanted()


def _credential_path() -> str:
    """The systemd credential holding the key, under its name or its pre-rebrand one; '' if none."""
    folder = os.environ.get("CREDENTIALS_DIRECTORY")
    for name in (CREDENTIAL_NAME, legacy_names.OLD_CREDENTIAL_NAME):
        candidate = os.path.join(folder, name) if folder else ""
        if candidate and os.path.exists(candidate):
            return candidate
    return ""


def enabled() -> bool:
    return bool(
        getattr(_override, "text", "")
        or legacy_names.getenv(KEY_ENV)
        or legacy_names.getenv(KEY_FILE_ENV)
        or _credential_path()
        or _own_key_wanted()
    )


@functools.lru_cache(maxsize=8)
def _raw_key(text: str, salt: bytes = _KDF_SALT) -> str:
    if len(text) < MIN_KEY_CHARS:
        raise DataKeyError(f"{KEY_ENV} must be at least {MIN_KEY_CHARS} characters")
    # One slow derivation per process; every connection then uses the raw key (no KDF cost)
    return hashlib.pbkdf2_hmac("sha256", text.encode("utf-8"), salt, _KDF_ROUNDS).hex()


def _key_sql(salt: bytes = _KDF_SALT) -> str:
    if not HAVE_SQLCIPHER:
        raise DataKeyError(f"{KEY_ENV} is set, but this build has no SQLCipher support")
    return "\"x'" + _raw_key(_key_text(), salt) + "'\""


def _opens_with(path: str, salt: bytes) -> bool:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15.0)
        try:
            conn.execute(f"PRAGMA key = {_key_sql(salt)}")
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            conn.close()
        return True
    except sqlite3.DatabaseError:
        return False


def is_plaintext(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(16) == SQLITE_HEADER
    except OSError:
        return False


def is_encrypted(path: str) -> bool:
    """A non-empty database file without the plain SQLite header."""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return False
    return len(head) == 16 and head != SQLITE_HEADER


def applies_to(path: str) -> bool:
    return os.path.basename(path) in ENCRYPTED_NAMES


def apply_key(conn: Any, path: str) -> None:
    """Keys a fresh connection to an AI database. Must run before any other statement.

    Plain files that are still waiting for conversion are opened without a key; new and
    encrypted files get the key."""
    if enabled() and applies_to(path) and not is_plaintext(path):
        salt = _salt_of(path) if is_encrypted(path) else _KDF_SALT  # a new file takes the current key
        conn.execute(f"PRAGMA key = {_key_sql(salt)}")


def connect(path: str, readonly: bool = False, **kwargs: Any) -> Any:
    """Opens an AI database (or any SQLite file) through the SQLCipher module, keyed when needed."""
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, **kwargs)
    else:
        conn = sqlite3.connect(path, **kwargs)
    try:
        apply_key(conn, path)
    except Exception:
        conn.close()
        raise
    return conn


def _verify(path: str) -> None:
    try:
        conn = connect(path, readonly=True, timeout=15.0)
        try:
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise DataKeyError(
            f"{os.path.basename(path)} is encrypted and {KEY_ENV} does not open it (wrong key?): {e}"
        ) from None


def _fsync_dir(path: str) -> None:
    try:
        fd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as e:
        logger.debug(f"[Encryption] could not sync the folder of {path}: {e}")


def _encrypt_in_place(path: str, old_salt: bytes | None = None) -> None:
    """A plain file encrypted under the key, or with `old_salt` a file keyed with an older salt
    encrypted again under the current one: copied into a new file, checked, then swapped in."""
    tmp = path + ".encrypting"
    for stale in (tmp, tmp + "-wal", tmp + "-shm"):
        if os.path.exists(stale):
            os.remove(stale)
    src = sqlite3.connect(path, timeout=60.0)
    try:
        if old_salt is not None:
            src.execute(f"PRAGMA key = {_key_sql(old_salt)}")
        src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        version = int(src.execute("PRAGMA user_version").fetchone()[0])
        quoted = tmp.replace("'", "''")
        src.execute(f"ATTACH DATABASE '{quoted}' AS enc KEY {_key_sql()}")
        src.execute("SELECT sqlcipher_export('enc')")
        src.execute(f"PRAGMA enc.user_version = {version}")
        src.execute("DETACH DATABASE enc")
    finally:
        src.close()
    os.chmod(tmp, 0o600)
    check = connect_encrypted(tmp, timeout=15.0)  # the copy must open with the key before it replaces the original
    try:
        check.execute("SELECT count(*) FROM sqlite_master").fetchone()
    finally:
        check.close()
    with open(tmp, "rb") as f:
        os.fsync(f.fileno())
    os.replace(tmp, path)
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(path + suffix)  # the plain WAL is empty after the checkpoint and would not match
        except FileNotFoundError:
            continue
    _fsync_dir(path)


def prepare(path: str) -> str:
    """Brings one AI database in line with the key: 'new', 'plain', 'encrypted' or 'converted'.

    Raises DataKeyError when an encrypted file cannot be opened."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return "new"
    if not enabled():
        if is_encrypted(path):
            raise DataKeyError(
                f"{os.path.basename(path)} is encrypted, but {KEY_ENV} is not set. "
                "Set the same key in the container settings and restart."
            )
        return "plain"
    if is_encrypted(path):
        if not _opens_with(path, _KDF_SALT) and _opens_with(path, legacy_names.OLD_KDF_SALT):
            logger.info("[Encryption] %s takes the current key salt…", os.path.basename(path))
            _encrypt_in_place(path, old_salt=legacy_names.OLD_KDF_SALT)
            _salts[path] = _KDF_SALT
            return "converted"
        _verify(path)
        return "encrypted"
    size_mb = os.path.getsize(path) / 1e6
    logger.info("[Encryption] Encrypting %s (%.0f MB)…", os.path.basename(path), size_mb)
    _encrypt_in_place(path)
    logger.info("[Encryption] %s is now encrypted at rest", os.path.basename(path))
    return "converted"


def prepare_in_background(path: str) -> None:
    """Runs prepare() on a thread; wait_ready() lets the database's users wait for it."""
    with _ready_lock:
        if path in _ready:
            return
        event = _ready[path] = threading.Event()

    def run() -> None:
        try:
            prepare(path)
        except Exception as e:
            _failed[path] = str(e)
            if isinstance(e, DataKeyError):  # the chip may only have been busy at the start
                _key_failed_at[path] = _now()
            logger.error(f"[Encryption] {e}")
        finally:
            event.set()

    threading.Thread(target=run, name="DataEncryption", daemon=True).start()


def wait_ready(path: str, timeout: float = 0.0) -> None:
    """Raises sqlite3.OperationalError while a background conversion runs or after it failed."""
    event = _ready.get(path)
    if event is not None and not event.wait(timeout):
        raise sqlite3.OperationalError("The AI index is being encrypted; try again in a few minutes.")
    if path in _failed:
        if _now() - _key_failed_at.get(path, float("inf")) >= RETRY_KEY_AFTER:
            _open_again(path)
            raise sqlite3.OperationalError("The AI index is being opened again; try again in a moment.")
        raise sqlite3.OperationalError(_failed[path])


def _open_again(path: str) -> None:
    """A key that could not be opened (the security chip was busy while the machine started) is
    asked for again, so one refusal does not keep the index shut until Kiboto restarts."""
    with _ready_lock:
        _failed.pop(path, None)
        _key_failed_at.pop(path, None)
        _ready.pop(path, None)
    prepare_in_background(path)


def status(path: str) -> str:
    """'off', 'encrypting', 'encrypted', 'plain' (waiting for conversion) or 'locked'."""
    if path in _failed:
        return "locked"
    event = _ready.get(path)
    if event is not None and not event.is_set():
        return "encrypting"
    if is_encrypted(path):
        return "encrypted"
    return "plain" if enabled() else "off"


_salts: dict[str, bytes] = {}  # path -> the salt it opens with, until prepare() encrypts it again


def _salt_of(path: str) -> bytes:
    """The salt an encrypted file opens with: the current one, or the one of before the rebrand on a
    file prepare() has not encrypted again yet. Everything a new version's start does before that
    (the snapshot, the schema migrations) opens such a file with its own key; with the current one
    it read as damaged and the new version stopped at once."""
    known = _salts.get(path)
    if known is not None:
        return known
    salt = _KDF_SALT
    if not _opens_with(path, _KDF_SALT) and _opens_with(path, legacy_names.OLD_KDF_SALT):
        salt = legacy_names.OLD_KDF_SALT
    _salts[path] = salt
    return salt


def copy(src: str, dst: str) -> None:
    """Consistent copy of a SQLite file that keeps it encrypted when it is encrypted, under the key it
    has: the snapshot taken before an update copies files still keyed the way of before."""
    keyed = enabled() and applies_to(src) and is_encrypted(src)
    if keyed:
        salt = _salt_of(src)
        s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30.0)
        s.execute(f"PRAGMA key = {_key_sql(salt)}")
    else:
        s = connect(src, readonly=True, timeout=30.0)
    try:
        d = sqlite3.connect(dst)
        try:
            if keyed:
                d.execute(f"PRAGMA key = {_key_sql(salt)}")
            s.backup(d)
        finally:
            d.close()
    finally:
        s.close()


def errors() -> tuple[type[BaseException], ...]:
    """Exception classes for code that may hold either a stdlib or a SQLCipher connection."""
    import sqlite3 as _std

    return (_std.Error, sqlite3.Error) if HAVE_SQLCIPHER else (_std.Error,)


def connect_encrypted(path: str, readonly: bool = True, **kwargs: Any) -> Any:
    """Opens an encrypted AI database under another name (e.g. a backup's temp copy) with the key."""
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, **kwargs)
    else:
        conn = sqlite3.connect(path, **kwargs)
    try:
        salt = _KDF_SALT if _opens_with(path, _KDF_SALT) or not _opens_with(path, legacy_names.OLD_KDF_SALT) else None
        conn.execute(f"PRAGMA key = {_key_sql(salt or legacy_names.OLD_KDF_SALT)}")  # a copy made before the new salt
    except Exception:
        conn.close()
        raise
    return conn
