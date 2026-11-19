"""Is a new password in a known data leak? (Have I Been Pwned's range list.)

Off unless turned on (backend/outside_checks.py). The password never leaves the NAS: its SHA-1
is taken here and only the first five of its forty characters are sent; the service answers with
every leaked hash that starts so (several hundred, padded so the answer's size says nothing) and
the comparison happens here. When the service cannot be reached the password is accepted: a
check that is down must not stop someone from changing a password.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable

import httpx

from backend import outside_checks

logger = logging.getLogger("Kiboto")

RANGE_URL = "https://api.pwnedpasswords.com/range/"
TIMEOUT = 4.0


def _fetch(prefix: str) -> str:
    res = httpx.get(RANGE_URL + prefix, headers={"Add-Padding": "true", "User-Agent": "Kiboto"}, timeout=TIMEOUT)
    res.raise_for_status()
    return res.text


def times_leaked(password: str, fetch: Callable[[str], str] | None = None) -> int | None:
    """How often the password appears in known leaks; None when the list could not be asked."""
    digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        body = (fetch or _fetch)(prefix)
    except (httpx.HTTPError, OSError, ValueError) as e:
        logger.info("leaked-password check: the list could not be asked (%s)", type(e).__name__)
        return None
    for line in body.splitlines():
        found, _, count = line.strip().partition(":")
        if found.upper() == suffix:
            try:
                return int(count)
            except ValueError:
                return 1
    return 0


def problem(password: str, fetch: Callable[[str], str] | None = None) -> str | None:
    """Why this password can't be used, when the check is on and the password is in a leak."""
    if not outside_checks.enabled("leaked_passwords"):
        return None
    count = times_leaked(password, fetch)
    if not count:
        return None
    return (
        f"That password appears in known data leaks ({count:,} times), so it is tried early in attacks. "
        "Please choose another."
    )
