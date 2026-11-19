"""The household guides quote numbers from the code; when a number changes, the guide must too."""

import os

from backend import config
from backend.services import compose_apply, docker_updates, heat_guard, offsite_backup, quiet_night, recycle_bin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _doc(name):
    with open(os.path.join(ROOT, "docs", name), encoding="utf-8") as fh:
        return " ".join(fh.read().split())  # line breaks inside a sentence do not matter


def test_apps_guide_numbers():
    text = _doc("APPS.md")
    assert f"kept running for {int(docker_updates.UPDATE_GRACE_SECS)} seconds" in text
    assert f"keeps running for {compose_apply.SETTLE_SECS} seconds" in text


def test_backup_guide_numbers():
    text = _doc("BACKUP.md")
    assert offsite_backup.RETRY_AFTER_SECS == 3600 and "again once an hour" in text
    assert offsite_backup.CATCH_UP_AFTER_SECS > 24 * 3600 and "missed for more than a day" in text


def test_files_guide_numbers():
    text = _doc("FILES.md")
    assert f"stays there for {recycle_bin.KEEP_DAYS} days" in text
    assert recycle_bin.MAX_SHARE_OF_DISK == 0.10 and "a tenth of its drive" in text
    assert recycle_bin.MIN_KEEP_SECS == 86400 and "stays in the bin for one day" in text


def test_people_guide_numbers():
    assert f"first password of {config.MIN_PASSWORD_LENGTH} characters or more" in _doc("PEOPLE.md")


def test_power_guide_too_hot_numbers():
    text = _doc("POWER.md")
    assert (
        f"An awake hard drive at {heat_guard.HDD_LIMIT_C} °C, or an NVMe drive at {heat_guard.NVME_LIMIT_C} °C" in text
    )
    assert f"stays that hot for {heat_guard.HOLD_SECS // 60} minutes" in text
    assert f"every drive is {heat_guard.REARM_MARGIN_C} °C under its limit" in text
    assert f"full speed from {config.HDD_CRITICAL_TEMP} °C (NVMe drives {config.NVME_CRITICAL_TEMP} °C)" in text


def test_hardware_guide_quiet_night_numbers(monkeypatch, tmp_path):
    from backend.services.fan_control import CPU_CRITICAL_C

    text = _doc("HARDWARE.md")
    monkeypatch.setattr(quiet_night, "SETTINGS_FILE", str(tmp_path / "none.json"))
    st = quiet_night.state()  # no settings file: the defaults
    assert f"between two times ({st['start']} to {st['end']} unless you change them)" in text
    assert f"as if the drives were {int(quiet_night.SHIFT_C)} °C cooler" in text
    assert (
        f"From {int(quiet_night.FULL_SHIFT_BELOW_C)} °C the difference shrinks, and from {int(quiet_night.NO_SHIFT_FROM_C)} °C"
        in text
    )
    assert (
        f"a hard drive reaches {config.HDD_CRITICAL_TEMP} °C, an NVMe drive {config.NVME_CRITICAL_TEMP} °C or the processor {CPU_CRITICAL_C} °C"
        in text
    )


def test_reaudit_guide_numbers():
    """The sections the 19 Nov re-audit added: electricity, damaged files, space per app, speed tests."""
    from backend.hardware.pal import scrub_parse
    from backend.services import app_storage, energy_use

    power = _doc("POWER.md")
    assert f"more than {int(energy_use.MAX_GAP_SECS)} seconds apart" in power
    assert f"kept for {energy_use.KEEP_DAYS} days" in power
    assert f"Up to {scrub_parse.MAX_DAMAGED_LISTED} files are listed" in _doc("STORAGE.md")
    assert f"stops after {int(app_storage.WALK_SECONDS)} seconds" in _doc("APPS.md")
    with open(
        os.path.join(ROOT, "frontend", "src", "components", "management", "speed-test.js"), encoding="utf-8"
    ) as fh:
        speed = fh.read()
    assert "LIMIT_MS = 4000" in speed and "i < 5" in speed
    network = _doc("NETWORK.md")
    assert "for up to 4 seconds" in network and "times five small requests" in network
