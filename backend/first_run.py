"""The first sign-in on a machine set up for Kiboto.

A fresh install keeps its first-time password in a file only root can read. On a box with no
screen and no keyboard nobody reads that file. On a managed host the first-time password is a code
that can be typed (three groups of four, no letters or digits that look alike), and the machine
shows it where only its owner looks: on its own screen (the login banner of the console) and to
whoever signs in to it over SSH. Both notices go when the person has chosen their own password."""

import os
import secrets

from backend import config, runtime
from backend.config import logger

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0, 1
ISSUE = "/etc/issue.d/kiboto.issue"  # shown above the console's login prompt; \4 is the address
MOTD = "/etc/motd.d/kiboto"  # shown after signing in over SSH
_TEXT = (
    "\nKiboto is ready to be set up.\n"
    "Open http://{where}:8082 in a browser and sign in as  admin  with this code:\n\n"
    "    {code}\n\n"
    "You then choose your own password, and this notice goes away.\n\n"
)


def new_code() -> str:
    """Twelve characters in three groups: about 60 bits, and sign-in attempts are limited."""
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(3))


def tidy(typed: str) -> str:
    """What was typed, as a code is written: capitals, no spaces, a dash after every four."""
    letters = "".join(ch for ch in typed.upper() if ch.isalnum())
    if len(letters) != 12 or any(ch not in ALPHABET for ch in letters):
        return typed
    return "-".join(letters[i : i + 4] for i in (0, 4, 8))


def waiting() -> bool:
    """True while nobody has chosen the admin's own password yet."""
    return os.path.exists(config.initial_password_file())


def where() -> str:
    """Where the person finds the first-time password: on the 'machine', or in the 'file'."""
    return "machine" if runtime.managed_host() else "file"


def show(code: str) -> bool:
    """Puts the code on the machine's screen and in its SSH greeting. Only on a managed host."""
    if not runtime.managed_host():
        return False
    for path, place in ((ISSUE, "\\4"), (MOTD, "this machine's address")):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(_TEXT.format(where=place, code=code))
            os.chmod(path, 0o644)
        except OSError as e:
            logger.warning("The first-time code could not be shown in %s: %s", path, e)
    return True


def clear() -> None:
    if not runtime.managed_host():
        return
    for path in (ISSUE, MOTD):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            logger.warning("The first-time notice %s could not be removed: %s", path, e)


def refresh() -> None:
    """At start: the notice is there while the first sign-in is waiting, and gone afterwards."""
    if not runtime.managed_host():
        return
    try:
        with open(config.initial_password_file(), encoding="utf-8") as f:
            code = f.read().strip()
    except OSError:
        code = ""
    if code:
        show(code)
    else:
        clear()
