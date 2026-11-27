"""#71: the front screen's bays page numbered the plain list of disks as bays: USB sticks and NVMe
drives took SATA bays, and a four-bay D4 showed six. It follows the chassis page's map now."""

from backend.hardware.chassis import ChassisEngine
from backend.services import lcd_pil, stats_collector

SDA = {"dev": "sda", "temp": 38}
NVME = {"dev": "nvme0n1", "temp": 41}
USB = {"dev": "sdc", "usb": True}


def test_the_bays_of_the_chassis_with_their_disks_then_the_m2_drives():
    stats = {"drive_bays": {"bays": ["sda", None, None, None], "m2": ["nvme0n1", "nvme9"]}}
    tiles = lcd_pil._bay_slots(stats, [SDA, NVME, USB])
    assert [label for label, _d in tiles] == ["BAY 1", "BAY 2", "BAY 3", "BAY 4", "M.2"]
    assert [d and d["dev"] for _l, d in tiles] == ["sda", None, None, None, "nvme0n1"]


def test_without_a_map_or_with_too_many_bays_the_list_as_before():
    assert len(lcd_pil._bay_slots({}, [SDA])) == 6
    big = {"drive_bays": {"bays": [None] * 12, "m2": []}}
    assert [label for label, _d in lcd_pil._bay_slots(big, [SDA, USB])][:2] == ["BAY 1", "BAY 2"]


def test_the_page_draws_the_d4s_four_bays():
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (lcd_pil.WIDTH, lcd_pil.HEIGHT))
    stats = {"disks": [SDA, NVME, USB], "drive_bays": {"bays": ["sda", None, None, None], "m2": ["nvme0n1"]}}
    lcd_pil._page_bays(ImageDraw.Draw(img), stats, lcd_pil.palette(None))


def test_the_map_is_read_at_most_once_a_minute(monkeypatch):
    calls = []

    def status():
        calls.append(1)
        return {"bays": [{"disk": {"dev": "sda"}}, {"disk": None}], "nvme_slots": [{"disk": {"dev": "nvme0n1"}}]}

    monkeypatch.setattr(ChassisEngine, "get_chassis_status", staticmethod(status))
    monkeypatch.setattr(stats_collector, "_BAYS", {"at": -1000.0, "value": None})
    assert stats_collector.drive_bays(now=0.0) == {"bays": ["sda", None], "m2": ["nvme0n1"]}
    assert stats_collector.drive_bays(now=30.0) == {"bays": ["sda", None], "m2": ["nvme0n1"]}
    assert len(calls) == 1

    def broken():
        raise OSError("lsblk")

    monkeypatch.setattr(ChassisEngine, "get_chassis_status", staticmethod(broken))
    assert stats_collector.drive_bays(now=100.0) == {"bays": ["sda", None], "m2": ["nvme0n1"]}  # kept
