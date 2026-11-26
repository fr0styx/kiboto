"""The Zettlab D4's light bar (issue #68): on the board's uart7, with the same frames as the D6/D8
bar. Its controller keeps the last effect in its own memory, so it is written only when the effect
changes, and the rainbow (a new colour many times a second) is not sent to it."""

import pytest

from backend.hardware import led

# captured by the reporter from ZettOS's own writes, and checked by sending it: solid red
SOLID_RED = bytes.fromhex("ffff06ff0000ff000067cd")


@pytest.fixture
def d4(tmp_path, monkeypatch):
    """A D4 whose uart7 is a file, so what is written can be read back."""
    uart = tmp_path / "ttyS7"
    uart.write_bytes(b"")
    monkeypatch.setattr(led, "D4_UARTS", (str(uart), str(tmp_path / "host-ttyS7")))
    monkeypatch.setattr(led, "_is_d4", lambda: True)
    monkeypatch.setattr(led._settings, "current", lambda key: "")  # no LED_PORT set
    monkeypatch.setattr(led, "serial", None)  # the file is opened as a plain file
    monkeypatch.setattr(led, "run_bounded", lambda *a, **k: None)  # no stty on a file
    led._close_serial_connection()
    monkeypatch.setattr(led, "_configured_ports", set())
    monkeypatch.setattr(led, "_last_connect_fail_time", 0.0)
    yield uart
    led._close_serial_connection()


def _written(uart) -> bytes:
    with led._serial_lock:
        if led._serial_handle is not None:
            led._serial_handle.flush()
    return uart.read_bytes()


def test_the_bar_is_found_on_the_boards_uart(d4):
    assert led.find_led_port() == str(d4)
    assert led.keeps_its_effect(str(d4)) is True


def test_without_its_uart_a_d4_takes_no_other_serial_device(d4):
    d4.unlink()
    assert led.find_led_port() is None  # not a Zigbee stick on ttyUSB0


def test_the_frame_is_the_one_zettos_sends(d4):
    ok, _ = led.send_led_packet(6, 255, 0, 0, 255, 0, 0, speed=0x67)
    assert ok and _written(d4) == SOLID_RED


def test_the_same_effect_is_written_once(d4):
    for _ in range(5):  # the stats loop asks every few seconds during night mode or an alert
        assert led.send_led_packet(0, 0, 0, 0, 0, 0, 0, 0)[0] is True
    assert len(_written(d4)) == 11
    led.send_led_packet(6, 255, 0, 0, 255, 0, 0, speed=0x67)
    led.send_led_packet(6, 255, 0, 0, 255, 0, 0, speed=0x67)
    assert _written(d4)[11:] == SOLID_RED


def test_after_a_reconnect_the_bar_is_told_again(d4, monkeypatch):
    sent = []

    class Port:
        def write(self, frame):
            sent.append(frame)

    monkeypatch.setattr(led, "_get_serial_connection", lambda port: Port())
    led.send_led_packet(6, 255, 0, 0, 255, 0, 0, speed=0x67)
    led.send_led_packet(6, 255, 0, 0, 255, 0, 0, speed=0x67)
    assert sent == [SOLID_RED]
    led._close_serial_connection()  # the port went away and came back
    led.send_led_packet(6, 255, 0, 0, 255, 0, 0, speed=0x67)
    assert sent == [SOLID_RED, SOLID_RED]


def test_a_failed_write_is_not_taken_for_a_sent_one(d4, monkeypatch):
    class Broken:
        def write(self, frame):
            raise OSError("the port went away")

    monkeypatch.setattr(led, "_get_serial_connection", lambda port: Broken())
    assert led.send_led_packet(6, 255, 0, 0, 255, 0, 0, speed=0x67)[0] is False
    assert led._last_frame == {}


def test_the_rainbow_is_not_sent_to_a_bar_that_keeps_its_effect(d4):
    ok, message = led.apply_led_state({"power": "on", "mode": "rainbow", "brightness": 50})
    assert ok is False and "keeps each effect in its own memory" in message
    assert not (led.Z_STATE.rainbow_thread and led.Z_STATE.rainbow_thread.is_alive())
    assert _written(d4) == b""


def test_its_own_effects_are_sent(d4):
    for mode, number in (("breathe", 1), ("flow", 2), ("chase", 3), ("gradient", 4), ("flashing", 5), ("solid", 6)):
        led.apply_led_state({"power": "on", "mode": mode, "color": "0000ff", "color2": "ff0000", "brightness": 100})
        assert _written(d4)[-11:][2] == number, mode


def test_a_d6_bar_is_written_every_time_as_before(tmp_path, monkeypatch):
    acm = tmp_path / "ttyACM0"
    acm.write_bytes(b"")
    monkeypatch.setattr(led, "find_led_port", lambda: str(acm))
    monkeypatch.setattr(led, "serial", None)
    monkeypatch.setattr(led, "run_bounded", lambda *a, **k: None)
    led._close_serial_connection()
    monkeypatch.setattr(led, "_configured_ports", set())
    monkeypatch.setattr(led, "_last_connect_fail_time", 0.0)
    try:
        led.send_led_packet(0, 0, 0, 0, 0, 0, 0, 0)
        led.send_led_packet(0, 0, 0, 0, 0, 0, 0, 0)
        assert len(_written(acm)) == 22
        assert led.keeps_its_effect(str(acm)) is False
    finally:
        led._close_serial_connection()


def test_the_page_is_told_not_to_offer_the_rainbow_there(client, auth_headers, monkeypatch):
    from backend.api import led as api

    monkeypatch.setattr(api, "find_led_port", lambda: "/dev/ttyS7")
    assert client.get("/api/led", headers=auth_headers).json()["rainbow_offered"] is False
    monkeypatch.setattr(api, "find_led_port", lambda: "/dev/ttyACM0")
    assert client.get("/api/led", headers=auth_headers).json()["rainbow_offered"] is True
    monkeypatch.setattr(api, "find_led_port", lambda: None)
    assert client.get("/api/led", headers=auth_headers).json()["rainbow_offered"] is True


def test_the_d4_is_asked_for_once(monkeypatch):
    calls = []

    def detect(allow_fallback=True):
        calls.append(allow_fallback)
        return "d4"

    monkeypatch.setattr("backend.hardware.storage.detect_chassis_model", detect)
    monkeypatch.setattr(led, "_d4", {"known": False, "value": False})
    assert led._is_d4() is True and led._is_d4() is True
    assert calls == [False]
    monkeypatch.setattr(led, "_d4", {"known": False, "value": False})
    monkeypatch.setattr("backend.hardware.storage.detect_chassis_model", lambda allow_fallback=True: "d8u")
    assert led._is_d4() is False

    def broken(allow_fallback=True):
        raise OSError("no device tree")

    monkeypatch.setattr(led, "_d4", {"known": False, "value": False})
    monkeypatch.setattr("backend.hardware.storage.detect_chassis_model", broken)
    assert led._is_d4() is False
