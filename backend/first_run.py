"""The first sign-in on a machine set up for Kiboto.

A fresh install keeps its first-time password in a file only root can read. On a box with no
screen and no keyboard nobody reads that file. On a managed host the first-time password is a code
that can be typed (three groups of four, no letters or digits that look alike), and the machine
shows it where only its owner looks: on its own screen (the login banner of the console) and to
whoever signs in to it over SSH. Both notices go when the person has chosen their own password."""

import os
import secrets
import shutil
import subprocess

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
    """Puts the code on the machine's screen and in its SSH greeting. Only on a managed host. The
    host door writes it (/etc is root's; Kiboto runs as the user kiboto, ADR 0006 step 9), from the
    code file it reads itself, so nothing else can be written there."""
    if not runtime.managed_host():
        return False
    from backend import door

    door.via("firstrun.notice", refresh_here)
    return True


def write_notice(code: str) -> None:
    """The notice files with this code (as root: the door, or Kiboto before step 9)."""
    for path, place in ((ISSUE, "\\4"), (MOTD, "this machine's address")):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.fchmod(fd, 0o600)  # also when the file was there before
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(_TEXT.format(where=place, code=code))
        except OSError as e:
            logger.warning("The first-time code could not be shown in %s: %s", path, e)
    _redraw()


def _redraw() -> None:
    """The console prints its banner when it draws the login prompt, which may have been before the
    notice changed: agetty --reload draws it again (as root, on a managed host only)."""
    agetty = shutil.which("agetty")
    if not agetty or os.geteuid() != 0 or not runtime.managed_host():
        return
    try:
        subprocess.run([agetty, "--reload"], capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        logger.info("The console could not draw its banner again: %s", e)


def clear() -> None:
    if not runtime.managed_host():
        return
    from backend import door

    door.via("firstrun.clear", clear_here)


def clear_here() -> None:
    for path in (ISSUE, MOTD):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            logger.warning("The first-time notice %s could not be removed: %s", path, e)
    _redraw()


def refresh() -> None:
    """At start: the notice is there while the first sign-in is waiting, and gone afterwards."""
    if not runtime.managed_host():
        return
    from backend import door

    door.via("firstrun.notice", refresh_here)


def refresh_here() -> None:
    """The notice from the code file: written while it is there, removed once it is gone."""
    try:
        with open(config.initial_password_file(), encoding="utf-8") as f:
            code = f.read().strip()
    except OSError:
        code = ""
    if code:
        write_notice(code)
    else:
        clear_here()
