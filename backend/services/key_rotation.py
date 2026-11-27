"""
Rotating the install's secret key (audit batch 0/1 follow-up).

The secret key encrypts two-factor secrets and backup passphrases, and signs short-lived
tokens. If someone may have copied it, a superadmin replaces it here: everything encrypted
with it is decrypted with the old key and encrypted again with a new one.

Crash-safe: the old key is written to secret.key.previous before anything changes, and
reading falls back to it, so data is readable whichever key it carries until the rotation
finishes and the previous key is removed.
"""

import logging
import os
import secrets
import time
from typing import Any

from backend import config

logger = logging.getLogger("Kiboto")


def previous_key_file() -> str:
    return config.SECRET_KEY_FILE + ".previous"


def _write_owner_only(path: str, text: str) -> None:
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def rotate_secret_key() -> dict[str, Any]:
    """Replaces the secret key and re-encrypts what it protects. Returns counts."""
    if os.environ.get("SECRET_KEY", "").strip():
        raise ValueError("The secret key is set by the SECRET_KEY environment variable; change it there.")
    old_key = str(config.SECRET_KEY or "")
    new_key = secrets.token_hex(32)
    _write_owner_only(previous_key_file(), old_key)
    _write_owner_only(config.SECRET_KEY_FILE, new_key)
    config.SECRET_KEY = new_key

    counts = reseal_everything()
    os.remove(previous_key_file())
    result = {"rotated_at": time.time(), "mfa_secrets": counts["mfa"], "backup_passphrases": counts["other"]}
    logger.warning("[Security] Secret key rotated; MFA secrets and stored passwords resealed")
    return result


def _resealed(value: Any) -> tuple[Any, int]:
    """A JSON value with every sealed string in it sealed again with the current key and box.
    A value that can't be opened (another install's, or damaged) is left as it is."""
    from backend import secret_box

    if isinstance(value, str) and secret_box.is_sealed(value):
        try:
            return secret_box.seal(secret_box.unseal(value)), 1
        except secret_box.SecretBoxError:
            return value, 0
    if isinstance(value, dict):
        out, n = {}, 0
        for k, v in value.items():
            out[k], c = _resealed(v)
            n += c
        return out, n
    if isinstance(value, list):
        items = [_resealed(v) for v in value]
        return [v for v, _ in items], sum(c for _, c in items)
    return value, 0


def _reseal_json_files() -> int:
    """Every settings file of Kiboto's own (the data folder's JSON files) with sealed values in it:
    new services keep theirs there too, so none is missed (SNMP, Dynamic DNS, NUT, iSCSI and Home
    Assistant were, and a key rotation left their secrets unreadable once the old key was gone)."""
    import glob

    from backend.fsutil import atomic_write_json, locked_json, read_json

    total = 0
    for path in sorted(glob.glob(os.path.join(config.DATA_DIR, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                if '"enc' not in f.read():
                    continue
        except OSError:
            continue
        with locked_json(path):
            data = read_json(path, None)
            new, n = _resealed(data)
            if n:
                atomic_write_json(path, new)
                total += n
    return total


def reseal_everything() -> dict[str, int]:
    """Seals every stored secret again with the current key: two-factor secrets in the users
    database, the settings files, and what services keep elsewhere. Returns counts."""
    from backend import secret_box
    from backend.users_db import _evict_user_caches, users_db_session

    mfa = 0
    with users_db_session(None) as conn:
        rows = conn.execute(
            "SELECT id, mfa_secret FROM users WHERE mfa_secret IS NOT NULL AND mfa_secret != ''"
        ).fetchall()
        for row in rows:
            value = str(row["mfa_secret"])
            if not secret_box.is_sealed(value):
                continue
            try:
                plain = secret_box.unseal(value)  # falls back to the previous key
            except secret_box.SecretBoxError:
                logger.warning("[Security] a stored two-factor secret could not be opened; left as it is")
                continue
            conn.execute("UPDATE users SET mfa_secret = ? WHERE id = ?", (secret_box.seal(plain), row["id"]))
            mfa += 1
    for row in rows:
        _evict_user_caches(row["id"])
    other = _reseal_json_files()
    from backend.services import ha_apps, ha_link, ha_state
    from backend.services.adguard_kids import reseal as reseal_adguard
    from backend.services.encrypted_folders import reseal as reseal_encrypted
    from backend.services.family_access import reseal as reseal_family
    from backend.services.family_signin import reseal as reseal_signin
    from backend.services.fleet import reseal as reseal_fleet
    from backend.services.offsite_backup import reseal_rest_passwords

    other += reseal_rest_passwords() + reseal_adguard() + reseal_encrypted() + reseal_family()
    other += reseal_fleet() + reseal_signin() + ha_link.reseal() + ha_state.reseal() + ha_apps.reseal()
    return {"mfa": mfa, "other": other}


BOX_UPGRADED = "secret_box_v2"  # in the data folder: values sealed before the rebrand were sealed again


def reseal_old_values() -> bool:
    """Once: what was sealed the way of before the rebrand ("enc1:") is sealed again as "enc2:".
    True when it ran now."""
    mark = os.path.join(config.DATA_DIR, BOX_UPGRADED)
    if os.path.exists(mark):
        return False
    counts = reseal_everything()
    _write_owner_only(mark, "done\n")
    logger.info("[Security] %s stored secret(s) sealed again with the current box", counts["mfa"] + counts["other"])
    return True
