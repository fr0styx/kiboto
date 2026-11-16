"""The HTTPS listener (audit A9): a second uvicorn server on the HTTPS port, serving the same app
with the Let's Encrypt certificate from backend/services/acme_dns.py. It runs beside the plain HTTP
server (which stays, for the LAN address and the LCD), without the app's start-up work (lifespan off),
and is restarted after a renewal so the new certificate is used."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger("Kiboto")
_lock = threading.Lock()
_server: Any = None
_thread: threading.Thread | None = None
_app: Any = None


def serving() -> bool:
    return _thread is not None and _thread.is_alive()


def start(app: Any = None, *, enabled: bool = False, cert: str = "", key: str = "", label: str = "") -> bool:
    """Starts the listener when HTTPS is on and the certificate files exist; True when it runs. The
    caller (backend/api/https.py) passes the certificate in: this module sits below the services."""
    import uvicorn

    from backend.config import SETTINGS

    global _server, _thread, _app
    with _lock:
        _app = app if app is not None else _app
        if _app is None or serving():
            return serving()
        if not enabled or not (cert and key and os.path.exists(cert) and os.path.exists(key)):
            return False
        cfg = uvicorn.Config(
            _app,
            host="0.0.0.0",
            port=int(SETTINGS.https_port),
            ssl_certfile=cert,
            ssl_keyfile=key,
            lifespan="off",
            log_level="warning",
            server_header=False,
            proxy_headers=False,
        )
        _server = uvicorn.Server(cfg)
        _thread = threading.Thread(target=_server.run, name="HTTPS", daemon=True)
        _thread.start()
        logger.info("HTTPS listener on :%s for %s", SETTINGS.https_port, label)
        return True


def stop(wait: float = 10.0) -> None:
    global _server, _thread
    with _lock:
        if _server is not None:
            _server.should_exit = True
        t = _thread
    if t is not None:
        t.join(wait)
    with _lock:
        _server, _thread = None, None


def restart(**kw: Any) -> bool:
    stop()
    return start(**kw)
