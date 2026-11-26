"""Kiboto OS: the fan watchdog beside the app runs in the host door, which outlives a hung web process."""

import json
import os

from backend import fan_watchdog
from backend.services import host_door


def test_the_door_watches_only_where_kiboto_can_drive_fans(monkeypatch):
    seen = []
    monkeypatch.setattr(fan_watchdog, "controller", lambda: "none")
    assert host_door.fan_watchdog(lambda *a, **k: seen.append(a)) is False and seen == []
    monkeypatch.setattr(fan_watchdog, "controller", lambda: "hwmon /sys/class/hwmon/hwmon8")
    assert host_door.fan_watchdog(lambda *a, **k: seen.append(a)) is True
    assert seen and seen[0][0].endswith(".json")  # the app's heartbeat file


def test_the_heartbeat_is_read_only_as_a_small_plain_file(tmp_path):
    beat = tmp_path / "beat.json"
    beat.write_text(json.dumps({"ts": 1.0, "released": False}))
    assert fan_watchdog.read_heartbeat(str(beat)) == {"ts": 1.0, "released": False}
    link = tmp_path / "link.json"
    link.symlink_to(beat)
    assert fan_watchdog.read_heartbeat(str(link)) is None  # through a link: not read
    big = tmp_path / "big.json"
    big.write_text(json.dumps({"ts": 1.0, "pad": "x" * 5000}))
    assert fan_watchdog.read_heartbeat(str(big)) is None
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    assert fan_watchdog.read_heartbeat(str(fifo)) is None  # not a plain file: never waited on
    (tmp_path / "bad.json").write_text("{")
    assert fan_watchdog.read_heartbeat(str(tmp_path / "bad.json")) is None
    assert fan_watchdog.read_heartbeat(str(tmp_path / "none.json")) is None
