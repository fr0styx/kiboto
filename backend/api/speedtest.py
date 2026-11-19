"""Speed between a device and this NAS (re-audit 19 Nov 2026, R2).

"Why is my NAS slow?" is nearly always the link between the device in someone's hand and the
box: Wi-Fi two rooms away, a 100 Mbit cable, a phone on mobile data. The page fetches random
bytes from here, sends some back and times a few small requests. Nothing is stored, nothing
reaches an outside service, and every signed-in person may run it: it measures their own link.
"""

import os
import time

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from backend.auth import AuthenticatedPrincipal, get_current_principal

router = APIRouter(tags=["Network & Switching"])

MAX_DOWNLOAD_MB = 200
_CHUNK = 256 * 1024
_POOL_BYTES = 4 * 1024 * 1024
_pool = b""


def _random_pool() -> bytes:
    """4 MB of random bytes, made once: nothing between here and the browser can compress them."""
    global _pool
    if not _pool:
        _pool = os.urandom(_POOL_BYTES)
    return _pool


def _chunks(total: int):
    pool = _random_pool()
    sent = 0
    while sent < total:
        start = sent % _POOL_BYTES
        piece = pool[start : start + min(_CHUNK, total - sent)]
        sent += len(piece)
        yield piece


@router.get("/network/speedtest/ping")
def speedtest_ping(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, float]:
    """A small answer to time (the delay to the NAS and back)."""
    return {"time": time.time()}


@router.get("/network/speedtest/download")
def speedtest_download(
    mb: int = Query(25, ge=1, le=MAX_DOWNLOAD_MB),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> StreamingResponse:
    """`mb` megabytes of random bytes; the browser times how fast they arrive and may stop early."""
    total = mb * 1024 * 1024
    return StreamingResponse(
        _chunks(total),
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store", "Content-Length": str(total), "Content-Encoding": "identity"},
    )


@router.post("/network/speedtest/upload")
async def speedtest_upload(
    request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, float]:
    """Reads what the browser sends and throws it away (the usual body limit applies)."""
    received = 0
    started = time.perf_counter()
    async for piece in request.stream():
        received += len(piece)
    return {"bytes": received, "seconds": round(time.perf_counter() - started, 4)}
