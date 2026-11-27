"""What rclone's SFTP and WebDAV servers keep of a sign-in is forgotten when a person's sign-in
changes.

Both ask Kiboto whether a sign-in is right (rclone_auth_proxy.py), then keep the answer for five
minutes, keyed on the name and renewed by every use; rclone's own documentation says a changed
password takes effect only when that runs out. Tried on Kiboto OS: a person removed and made again
under the same name was refused with the right password, because rclone still held the earlier
sign-in, so the old password would have opened it; a changed password or a person turned off
would have kept working the same way. So whichever of the two is on starts again, which forgets
all it kept; whoever is signed in over SFTP or WebDAV at that moment signs in again."""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


def again() -> list[str]:
    """Starts the SFTP and WebDAV servers that are on again. Returns the ones it started again."""
    from backend.services.sftp_engine import get_sftp_engine
    from backend.services.webdav_engine import get_webdav_engine

    done = []
    for name, engine in (("sftp", get_sftp_engine), ("webdav", get_webdav_engine)):
        try:
            if engine().forget_sign_ins():
                done.append(name)
        except (OSError, RuntimeError, ValueError):
            logger.warning(
                "[Sign-in] %s was not started again: an old sign-in may work a few minutes", name, exc_info=True
            )
    return done


def forget(username: str = "") -> None:
    """users_db's hook for a changed sign-in: in the background, so the change itself does not wait."""
    threading.Thread(target=again, name="FileSignInsForget", daemon=True).start()
