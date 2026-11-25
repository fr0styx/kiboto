import asyncio
import json
import mmap
import os
import struct
import threading
import time

from backend.config import BUTTON_CFG_FILE, HOST_DEV, logger
from backend.ignored_errors import ignored
from backend.services.copy_engine import _do_copy, copy_dest
from backend.state import Z_STATE, add_event, event_text

BUTTON_POLL_SECS = 0.25  # PERF-5: was 0.1; the register has no interrupt, so it is read


def _next_lcd_page() -> None:
    """A press of the front button with nothing to copy: the LCD's next page, in the activity log."""
    new_page = Z_STATE.cycle_lcd_page()
    add_event(
        "info",
        "LCD Page Switched",
        f"Display cycled to Page {new_page} via front hardware button.",
        event_text("button_page", page=new_page),
    )


def button_listener_daemon():
    import platform

    from backend.hardware.fans import is_zettlab_appliance

    if not is_zettlab_appliance():
        logger.debug("[button_listener] Non-appliance hardware detected; skipping hardware button mapping.")
        return

    model = ""
    try:
        from backend.hardware.storage import detect_chassis_model

        model = detect_chassis_model(allow_fallback=False)
    except Exception:
        ignored("backend.services.button_listener.button_listener_daemon")
    if model == "d4":
        # the D4 (RK3588) has no register: its COPY button is a gpio-keys input key
        key = gpio_key_device()
        if key:
            logger.info("[Kiboto] The copy button on the D4 is read from %s", key)
            watch_key(key)
        else:
            logger.info("[Kiboto] The D4's copy button (gpio-keys) is not visible here; pass /dev/input to read it")
        return
    if model in ("generic", "diy"):
        logger.debug("[button_listener] Chassis %s does not use MMIO button mapping.", model)
        return
    if platform.machine().lower() not in ("x86_64", "amd64"):
        logger.debug("[button_listener] Non-x86_64 architecture detected; skipping MMIO hardware button mapping.")
        return

    MMIO_BASE = 0xE0D20000
    COPY_OFFSET = 0x6C0

    from backend.hardware import hw_client

    if hw_client.available(force=True):  # SEC-24: the helper holds /dev/mem
        logger.info("[Kiboto] The copy button on chassis %s is read through the hardware helper", model)
        _poll_button(lambda: int(hw_client.call("button")["value"]))
        return

    try:
        mem_cands = [
            "/dev/mem",
            os.path.join(HOST_DEV, "mem"),
            "/host/dev/mem",
        ]
        fd = None
        last_err = None
        for p in mem_cands:
            if os.path.exists(p):
                try:
                    fd = os.open(p, os.O_RDWR | os.O_SYNC)
                    break
                except Exception as err:
                    last_err = err
                    continue
        if fd is None:
            if last_err:
                raise last_err
            fd = os.open(os.path.join(HOST_DEV, "mem"), os.O_RDWR | os.O_SYNC)
        mem = mmap.mmap(fd, 4096, offset=MMIO_BASE)
        logger.info(f"[Kiboto] Successfully initialized MMIO hardware copy button listener on chassis {model}")
    except PermissionError as pe:
        from backend import runtime

        if runtime.without_root():
            logger.info("[Kiboto] The front COPY button is not read on Kiboto OS yet; copies start from the app.")
            return
        logger.warning(
            f"[Kiboto] Hardware button mapping failed: {pe}. "
            "Docker container lacks cgroup access to /dev/mem. "
            "Add --device-cgroup-rule='c 1:1 rwm' to container Extra Parameters in Unraid."
        )
        return
    except Exception as e:
        logger.info(f"[Kiboto] Hardware button mapping failed: {e}")
        return

    _poll_button(lambda: struct.unpack("<I", mem[COPY_OFFSET : COPY_OFFSET + 4])[0])


def _poll_button(read_value) -> None:
    """Watches the copy button: read_value() gives its 32-bit register (from /dev/mem or the helper)."""
    last_state = 1
    while True:
        try:
            copy_val = read_value()
            current_state = (copy_val & 2) >> 1

            if current_state == 0 and last_state == 1:
                # Hardware button mechanical debounce delay
                time.sleep(0.05)
                copy_val_check = read_value()
                if (copy_val_check & 2) >> 1 != 0:
                    last_state = 1
                    continue

                handle_press()

                # Debounce to prevent multi-triggering while holding button down
                time.sleep(0.3)
        except Exception as e:
            logger.debug(f"Silenced exception: {e}")
        time.sleep(BUTTON_POLL_SECS)


def handle_press() -> None:
    """A press of the front COPY button: copy the card when the button copies, else the LCD's next page."""
    cfg = {
        "enabled": False,
        "source": "sd",
        "dest": copy_dest(None),
        "use_exif": True,
        "verify_checksum": True,
        "on_collision": "skip",
        "action": "copy",
    }
    if os.path.exists(BUTTON_CFG_FILE):
        try:
            with open(BUTTON_CFG_FILE) as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    cfg.update(saved)
        except (json.JSONDecodeError, OSError) as read_err:
            logger.warning(f"[ButtonListener] Could not read {BUTTON_CFG_FILE}: {read_err}")

    is_enabled = bool(cfg.get("enabled", False))
    # Action defaults to "copy" if enabled, or "cycle_lcd" if disabled
    btn_action = cfg.get("action")
    if not btn_action:
        btn_action = "copy" if is_enabled else "cycle_lcd"

    logger.info(
        f"[ButtonListener] Physical front button pressed: enabled={is_enabled}, "
        f"action={btn_action}, copy_active={Z_STATE.copy_active}"
    )

    if is_enabled and not Z_STATE.copy_active and btn_action == "copy":
        from backend.services.copy_engine import read_media_slots

        slots = read_media_slots()
        src_slot = str(cfg.get("source", "sd")).lower().strip()
        slot_info = slots.get(src_slot, {})
        card_size = slot_info.get("size", 0)

        if card_size > 0:
            Z_STATE.pending_ingest = None
            Z_STATE.copy_active = True
            Z_STATE.copy_status = "copying"
            Z_STATE.ui_wake.set()
            slot_label = "SD Card" if src_slot == "sd" else "TF Card (MicroSD)"
            target_dir = copy_dest(cfg.get("dest"))
            add_event(
                "info",
                "Copy Started",
                f"Physical COPY button pressed. Starting ingest from {slot_label} to {target_dir}...",
                event_text("button_copy", slot=slot_label, dest=target_dir),
            )
            logger.info(f"[ButtonListener] Dispatched copy ingest thread for {slot_label} -> {target_dir}")
            threading.Thread(
                target=lambda c: asyncio.run(_do_copy(c)),
                args=(dict(cfg),),
                daemon=True,
                name="CopyWorker",
            ).start()
        else:
            add_event(
                "warning",
                "No Media Detected",
                f"Front-panel COPY button pressed, but no media card is detected in {src_slot.upper()} slot.",
                event_text("button_no_card", slot=src_slot.upper()),
            )
            _next_lcd_page()
    else:
        _next_lcd_page()


COPY_KEY_CODE = 2  # the D4's front COPY button in gpio-keys (KEY_1)
EV_KEY = 1
_EVENT = struct.Struct("llHHi")  # struct input_event on a 64-bit kernel: timeval, type, code, value


def gpio_key_device() -> str | None:
    """The input device of the board's gpio-keys (the D4's COPY button); None if not visible."""
    import glob

    from backend.config import HOST_SYS

    for ev in sorted(glob.glob(os.path.join(HOST_SYS, "class/input/event*"))):
        try:
            with open(os.path.join(ev, "device", "name")) as f:
                name = f.read().strip()
        except OSError:
            continue
        if name == "gpio-keys":
            path = os.path.join(HOST_DEV, "input", os.path.basename(ev))
            if os.path.exists(path):
                return path
    return None


def watch_key(path: str, code: int = COPY_KEY_CODE) -> None:
    """Reads key events from `path` until it closes: each press of `code` (not its repeats or its
    release) is one press of the button."""
    try:
        with open(path, "rb", buffering=0) as f:
            while True:
                data = f.read(_EVENT.size)
                if len(data) < _EVENT.size:
                    return
                _sec, _usec, kind, key, value = _EVENT.unpack(data)
                if kind == EV_KEY and key == code and value == 1:
                    try:
                        handle_press()
                    except (OSError, ValueError, KeyError, RuntimeError) as e:
                        logger.warning("[ButtonListener] the copy button press failed: %s", e)  # the next one counts
    except OSError as e:
        logger.info("[Kiboto] The copy button could not be read from %s: %s", path, e)
