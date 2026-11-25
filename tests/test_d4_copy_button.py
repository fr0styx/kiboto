"""The Zettlab D4's COPY button is a gpio-keys input key (code 2), not a register (#68)."""

import struct

from backend.services import button_listener as bl


def _events(path, items):
    with open(path, "wb") as f:
        for kind, code, value in items:
            f.write(struct.pack("llHHi", 0, 0, kind, code, value))


def test_one_press_is_one_copy(tmp_path, monkeypatch):
    presses = []
    monkeypatch.setattr(bl, "handle_press", lambda: presses.append(1))
    ev = tmp_path / "event3"
    _events(
        ev,
        [
            (bl.EV_KEY, 2, 1),  # press
            (0, 0, 0),  # sync
            (bl.EV_KEY, 2, 2),  # held: repeat
            (bl.EV_KEY, 2, 0),  # release
            (bl.EV_KEY, 116, 1),  # another key (power)
            (bl.EV_KEY, 2, 1),  # a second press
        ],
    )
    bl.watch_key(str(ev))
    assert presses == [1, 1]


def test_a_failed_press_does_not_stop_the_watch(tmp_path, monkeypatch):
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("no card")  # a press can fail; the watch goes on

    monkeypatch.setattr(bl, "handle_press", boom)
    ev = tmp_path / "event3"
    _events(ev, [(bl.EV_KEY, 2, 1), (bl.EV_KEY, 2, 1)])
    bl.watch_key(str(ev))
    assert calls == [1, 1]


def test_the_gpio_keys_device_is_found(tmp_path, monkeypatch):
    sys_root, dev_root = tmp_path / "sys", tmp_path / "dev"
    for n, name in ((0, "rk805 pwrkey"), (1, "adc-keys"), (3, "gpio-keys")):
        d = sys_root / "class" / "input" / f"event{n}" / "device"
        d.mkdir(parents=True)
        (d / "name").write_text(name + "\n")
        (dev_root / "input").mkdir(parents=True, exist_ok=True)
        (dev_root / "input" / f"event{n}").write_text("")
    monkeypatch.setattr("backend.config.HOST_SYS", str(sys_root))
    monkeypatch.setattr(bl, "HOST_DEV", str(dev_root))
    assert bl.gpio_key_device() == str(dev_root / "input" / "event3")


def test_the_d4_reads_its_key_and_not_the_register(monkeypatch):
    seen = []
    monkeypatch.setattr("backend.hardware.fans.is_zettlab_appliance", lambda: True)
    monkeypatch.setattr("backend.hardware.storage.detect_chassis_model", lambda allow_fallback=False: "d4")
    monkeypatch.setattr(bl, "gpio_key_device", lambda: "/dev/input/event3")
    monkeypatch.setattr(bl, "watch_key", lambda path: seen.append(path))
    monkeypatch.setattr(bl, "_poll_button", lambda read: seen.append("register"))
    bl.button_listener_daemon()
    assert seen == ["/dev/input/event3"]


# --- one press, every outcome (the same for the D4's key and the x86 register) ----------------

import json  # noqa: E402

import pytest  # noqa: E402

from backend.state import Z_STATE  # noqa: E402


@pytest.fixture
def press(tmp_path, monkeypatch):
    """handle_press with a button file, a card of `size` in the SD slot, and recorded effects."""
    seen = {"threads": [], "pages": 0, "events": []}

    class FakeThread:
        def __init__(self, target, args, **kw):
            seen["threads"].append(args[0])

        def start(self):
            pass

    monkeypatch.setattr(bl.threading, "Thread", FakeThread)
    monkeypatch.setattr(bl, "_next_lcd_page", lambda: seen.__setitem__("pages", seen["pages"] + 1))
    monkeypatch.setattr(bl, "add_event", lambda level, title, *a, **k: seen["events"].append(title))
    monkeypatch.setattr(Z_STATE, "copy_active", False)
    monkeypatch.setattr(Z_STATE, "pending_ingest", None)
    cfg_file = tmp_path / "button_state.json"
    monkeypatch.setattr(bl, "BUTTON_CFG_FILE", str(cfg_file))

    def run(cfg=None, size=0, raw=None):
        if raw is not None:
            cfg_file.write_text(raw)
        elif cfg is not None:
            cfg_file.write_text(json.dumps(cfg))
        monkeypatch.setattr(
            "backend.services.copy_engine.read_media_slots", lambda: {"sd": {"size": size}, "tf": {"size": 0}}
        )
        bl.handle_press()
        return seen

    return run


def test_a_press_with_a_card_starts_the_copy(press):
    seen = press({"enabled": True, "dest": "/mnt/storage/Photos"}, size=64_000_000_000)
    assert len(seen["threads"]) == 1 and seen["threads"][0]["dest"] == "/mnt/storage/Photos"
    assert seen["events"] == ["Copy Started"] and seen["pages"] == 0
    assert Z_STATE.copy_active is True


def test_a_press_without_a_card_says_so_and_turns_the_page(press):
    seen = press({"enabled": True}, size=0)
    assert seen["threads"] == [] and seen["events"] == ["No Media Detected"] and seen["pages"] == 1


def test_a_press_with_copying_off_turns_the_page(press):
    seen = press({"enabled": False, "action": ""}, size=64_000_000_000)
    assert seen["threads"] == [] and seen["pages"] == 1


def test_an_unreadable_button_file_is_the_defaults(press):
    seen = press(raw="{not json", size=64_000_000_000)
    assert seen["threads"] == [] and seen["pages"] == 1  # copying is off by default


def test_the_d4_without_its_key_says_how_to_pass_it(monkeypatch, caplog):
    monkeypatch.setattr("backend.hardware.fans.is_zettlab_appliance", lambda: True)
    monkeypatch.setattr("backend.hardware.storage.detect_chassis_model", lambda allow_fallback=False: "d4")
    monkeypatch.setattr(bl, "gpio_key_device", lambda: None)
    monkeypatch.setattr(bl, "watch_key", lambda path: pytest.fail("no key to watch"))
    bl.button_listener_daemon()
    assert any("/dev/input" in r.getMessage() for r in caplog.records)


def test_a_diy_box_has_no_button(monkeypatch):
    monkeypatch.setattr("backend.hardware.fans.is_zettlab_appliance", lambda: True)
    monkeypatch.setattr("backend.hardware.storage.detect_chassis_model", lambda allow_fallback=False: "diy")
    monkeypatch.setattr(bl, "watch_key", lambda path: pytest.fail("no key"))
    monkeypatch.setattr(bl, "_poll_button", lambda read: pytest.fail("no register"))
    bl.button_listener_daemon()


def test_an_arm_box_with_a_register_model_is_not_read_as_x86(monkeypatch):
    import platform

    monkeypatch.setattr("backend.hardware.fans.is_zettlab_appliance", lambda: True)
    monkeypatch.setattr("backend.hardware.storage.detect_chassis_model", lambda allow_fallback=False: "d8u")
    monkeypatch.setattr(platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(bl, "_poll_button", lambda read: pytest.fail("no register on arm"))
    bl.button_listener_daemon()


def test_a_key_device_that_cannot_be_opened_ends_the_watch(tmp_path, caplog):
    bl.watch_key(str(tmp_path / "gone"))
    assert any("could not be read" in r.getMessage() for r in caplog.records)


def test_an_input_device_without_a_name_is_skipped(tmp_path, monkeypatch):
    (tmp_path / "sys" / "class" / "input" / "event0").mkdir(parents=True)
    monkeypatch.setattr("backend.config.HOST_SYS", str(tmp_path / "sys"))
    assert bl.gpio_key_device() is None
