"""
Encryption at rest for small secrets stored in the users database (SEC-14).

TOTP seeds were stored in plain text, so anyone who got a copy of users.db (a
backup, a snapshot, a readable appdata share) could generate valid 2FA codes.
They are now sealed with AES-256-GCM under a key derived from the install's
SECRET_KEY (data/secret.key). Values without the "enc1:" prefix are legacy
plain text and are read as-is until migrate_plaintext_mfa_secrets() seals them.
"""

import base64
import hashlib
import logging
import os
from collections.abc import Callable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend import config, legacy_names

logger = logging.getLogger("Kiboto")

PREFIX = "enc2:"
OLD_PREFIX = "enc1:"  # sealed before the rebrand, under the old key derivation: read, and re-sealed once
_AAD = b"kiboto:secret:v2"


class SecretBoxError(ValueError):
    pass


def _key(secret: str | None = None) -> bytes:
    secret = str(secret if secret is not None else (getattr(config, "SECRET_KEY", "") or ""))
    if not secret:
        raise SecretBoxError("SECRET_KEY is not set")
    return hashlib.sha256(b"kiboto-secret-box-v2:" + secret.encode("utf-8")).digest()


def _derived_before(secret: str | None = None) -> bytes:
    secret = str(secret if secret is not None else (getattr(config, "SECRET_KEY", "") or ""))
    if not secret:
        raise SecretBoxError("SECRET_KEY is not set")
    return hashlib.sha256(legacy_names.OLD_BOX_KEY_START + secret.encode("utf-8")).digest()


def _box_for(value: str) -> tuple[int, Callable[[str | None], bytes], bytes]:
    """How a sealed value was sealed: (prefix length, key function, associated data)."""
    if value.startswith(OLD_PREFIX):
        return len(OLD_PREFIX), _derived_before, legacy_names.OLD_BOX_AAD
    return len(PREFIX), _key, _AAD


def _previous_secret() -> str:
    """The key before a rotation that hasn't finished (see services/key_rotation.py)."""
    try:
        with open(str(getattr(config, "SECRET_KEY_FILE", "")) + ".previous", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def is_sealed(value: str) -> bool:
    return bool(value) and value.startswith((PREFIX, OLD_PREFIX))


def is_old(value: str) -> bool:
    """Sealed the way of before the rebrand: re-sealed by key_rotation.reseal_everything."""
    return bool(value) and value.startswith(OLD_PREFIX)


def seal(plain: str) -> str:
    if not plain:
        return ""
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plain.encode("utf-8"), _AAD)
    return PREFIX + base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def unseal(value: str) -> str:
    if not value or not is_sealed(value):
        return value or ""
    head, key, aad = _box_for(value)
    try:
        raw = base64.urlsafe_b64decode(value[head:].encode("ascii"))
    except ValueError as e:
        raise SecretBoxError("A stored secret is damaged") from e
    for secret in (None, _previous_secret()):
        if secret == "":
            continue
        try:
            return AESGCM(key(secret)).decrypt(raw[:12], raw[12:], aad).decode("utf-8")
        except (InvalidTag, ValueError):
            continue
    raise SecretBoxError("Could not decrypt a stored secret (was SECRET_KEY changed?)")


def unseal_with(value: str, secret: str) -> str:
    """Opens a value sealed on another install, with that install's key: a second NAS that takes
    over reads the first one's two-factor secrets this way. Plain values pass, as in unseal()."""
    if not value or not is_sealed(value):
        return value or ""
    head, key, aad = _box_for(value)
    try:
        raw = base64.urlsafe_b64decode(value[head:].encode("ascii"))
        return AESGCM(key(secret)).decrypt(raw[:12], raw[12:], aad).decode("utf-8")
    except (InvalidTag, ValueError) as e:
        raise SecretBoxError("A secret from the other NAS could not be opened") from e


def migrate_plaintext_mfa_secrets(db_path: str = "") -> int:
    """Seals every TOTP seed still stored in plain text. Returns how many were sealed."""
    from backend.users_db import users_db_session

    sealed = 0
    with users_db_session(db_path or None) as conn:
        rows = conn.execute("SELECT id, mfa_secret FROM users WHERE COALESCE(mfa_secret, '') != ''").fetchall()
        for row in rows:
            if not is_sealed(row["mfa_secret"]):
                conn.execute("UPDATE users SET mfa_secret = ? WHERE id = ?", (seal(row["mfa_secret"]), row["id"]))
                sealed += 1
    if sealed:
        logger.info("[Security] Encrypted %s stored two-factor secret(s)", sealed)
    return sealed
