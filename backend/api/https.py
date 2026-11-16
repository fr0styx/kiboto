"""HTTPS at home settings, "Get a certificate", and the daily renewal (audit A9)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend import tls_server
from backend.auth import require_scope
from backend.config import SETTINGS, logger
from backend.services import acme_dns

router = APIRouter(tags=["Network & Switching"])


class HttpsIn(BaseModel):
    enabled: bool = False
    staging: bool = False


def start_tls(app: Any = None) -> bool:
    """The HTTPS listener with the current certificate (called at start and after a change)."""
    st = acme_dns.state()
    cert, key = acme_dns.cert_paths()
    return tls_server.start(app, enabled=st["enabled"], cert=cert, key=key, label=st.get("hostname", ""))


def restart_tls() -> bool:
    tls_server.stop()
    return start_tls()


def _out(st: dict[str, Any]) -> dict[str, Any]:
    return {**st, "port": int(SETTINGS.https_port), "serving": tls_server.serving(), "days_left": acme_dns.days_left()}


@router.get("/network/https", dependencies=[Depends(require_scope("system:view"))])
def get_https() -> dict[str, Any]:
    return _out(acme_dns.public_state())


@router.put("/network/https", dependencies=[Depends(require_scope("system:config"))])
def put_https(req: HttpsIn) -> dict[str, Any]:
    st = acme_dns.save(req.enabled, req.staging)
    if req.enabled:
        start_tls()
    else:
        tls_server.stop()
    return _out(st)


@router.post("/network/https/certificate", dependencies=[Depends(require_scope("system:config"))])
async def get_certificate() -> dict[str, Any]:
    """Asks Let's Encrypt now (about a minute: the DNS record needs time to spread)."""
    st = await asyncio.to_thread(acme_dns.issue)
    if not st["last_error"] and st["enabled"]:
        await asyncio.to_thread(restart_tls)
    return _out(st)


async def renew_loop() -> None:
    """Once an hour: renew when 30 days are left (tried at most once a day), then reload."""
    while True:
        await asyncio.sleep(3600)
        try:
            if acme_dns.renew_due(time.time()):
                st = await asyncio.to_thread(acme_dns.issue)
                if not st["last_error"]:
                    await asyncio.to_thread(restart_tls)
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning("Certificate renewal failed: %s", e)
