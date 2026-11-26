from fastapi import APIRouter, Depends

from backend.auth import require_scope
from backend.config import LED_STATE_FILE
from backend.fsutil import atomic_write_json, read_json
from backend.hardware.led import apply_led_state, find_led_port, keeps_its_effect
from backend.models.schemas import LedConfigRequest

router = APIRouter(tags=["ARGB Lighting"])


def _load_led():
    cur = read_json(LED_STATE_FILE, {})
    return cur if isinstance(cur, dict) else {}


def _offered() -> dict:
    """What this bar takes, for the page: the rainbow is not offered where the bar keeps its effect."""
    return {"rainbow_offered": not keeps_its_effect(find_led_port())}


@router.get("/led", dependencies=[Depends(require_scope("hardware:read", "system:view"))])
def get_led():
    return {**_load_led(), **_offered()}


@router.post("/led", dependencies=[Depends(require_scope("hardware:rgb"))])
def post_led(req: LedConfigRequest):
    data = req.model_dump(exclude_unset=True)
    cur_led = _load_led()
    cur_led.update(data)
    ok, msg = apply_led_state(cur_led)
    atomic_write_json(LED_STATE_FILE, cur_led)
    return {"status": "ok" if ok else "error", "message": msg, **cur_led, **_offered()}
