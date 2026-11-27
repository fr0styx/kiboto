"""#71: the built-in front-screen renderer drew its five cards and the drive strip whatever layout
was chosen in Settings. It follows the shown modules, their order and size now."""

from PIL import Image, ImageDraw

from backend.services import lcd_pil


def test_the_default_layout_is_the_five_cards_and_the_strip():
    cards, disks = lcd_pil.overview_plan(None)
    assert [m for m, _u in cards] == ["metric-storage", "metric-cpu", "metric-mem", "metric-fans", "metric-net"]
    assert all(u == 1.0 for _m, u in cards) and disks is True


def test_only_shown_modules_in_their_order_and_a_compact_one_narrower():
    layout = {
        "order": ["metric-net", "metric-cpu", "metric-disks", "unknown", "metric-storage"],
        "vis": {"metric-mem": False, "metric-fans": False, "metric-disks": False},
        "sizes": {"metric-cpu": "compact"},
    }
    cards, disks = lcd_pil.overview_plan(layout)
    assert cards == [("metric-net", 1.0), ("metric-cpu", 0.6), ("metric-storage", 1.0)]
    assert disks is False


def test_the_page_draws_any_layout():
    stats = {
        "storage": {"pct": 40, "used": "4 TB", "total": "10 TB"},
        "cpu": {"util": 12, "temp": 45, "load_avg": [0.5]},
        "mem": {"pct": 30, "used_gb": 4, "total_gb": 16},
        "fans": [1200, {"label": "CPU", "rpm": None}],
        "uptime": "2d",
        "net": {"rx_bytes_sec": 1000, "tx_bytes_sec": 2000},
        "disks": [{"dev": "sda", "temp": 38}],
    }
    c = lcd_pil.palette(None)
    for layout in (
        None,
        {"vis": {"metric-disks": False}},
        {"vis": {m: False for m in ("metric-storage", "metric-cpu", "metric-mem", "metric-fans", "metric-net")}},
        {"vis": {"metric-fans": True}, "sizes": {"metric-fans": "compact"}, "order": ["metric-fans"]},
    ):
        img = Image.new("RGB", (lcd_pil.WIDTH, lcd_pil.HEIGHT))
        lcd_pil._page_overview(ImageDraw.Draw(img), {**stats, "layout": layout, "fans": []} if layout else stats, c)
        assert img.getbbox() is not None  # something was drawn
