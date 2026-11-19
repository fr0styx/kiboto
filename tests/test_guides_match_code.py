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


def test_scripts_guide_numbers():
    """docs/SCRIPTS.md says what the service does: its limits and what a limited script cannot reach."""
    from backend.services import user_scripts as us

    text = _doc("SCRIPTS.md")
    assert f"30 unless you change it, at most {us.MAX_TIMEOUT_MIN}" in text and us.DEFAULT_TIMEOUT_MIN == 30
    assert f"Up to {us.MAX_SCRIPTS} scripts, each up to {us.MAX_BODY_BYTES // 1024} KB of text" in text
    assert f"the last {us.OUTPUT_KEPT_BYTES // 1024} KB" in text and f"The last {us.RUNS_KEPT} runs" in text
    assert us.MAX_AT_ONCE == 2 and "Two scripts run at the same time at most" in text
    # each thing the guide says a limited script cannot do is a step of the limit
    for said, step in [
        ("scratch folder (`/tmp`)", "tmpfs /tmp"),
        ("cannot see Kiboto's own settings", 'tmpfs "$DATA"'),
        ("cannot reach the drives themselves", "tmpfs /dev"),
        ("cannot start or change your apps", "docker.sock"),
        ("Everything else is read-only", "remount,bind,ro"),
        ("cannot give itself the rights back", "setpriv"),
    ]:
        assert said in text and step in us.LIMIT_WRAP, said
    assert "is not started rather than started without its limit" in text and "exit 97" in us.LIMIT_WRAP


def test_new_drive_check_guide():
    """docs/STORAGE.md, "Checking a new drive": its numbers and its three answers are the code's."""
    from backend.services import drive_check as dc

    text = _doc("STORAGE.md")
    assert f"within {dc.HEAT_MARGIN_C} °C of the temperature Kiboto treats as critical" in text
    assert f"The last {dc.RESULTS_KEPT} results of each drive are kept" in text
    assert dc.MAX_AT_ONCE == 2 and "Two drives can be checked at once" in text
    assert "Kiboto never starts this check by itself" in text and "nothing is written to the drive" in text
    assert set(dc.WATCHED) == {"realloc", "pending", "offline", "crc", "nvme_media_err"}
    for said in ("**Good to use**", "**Do not trust it with data**", "**The cable or the bay**"):
        assert said in text, said


def test_iscsi_guide_numbers():
    """docs/ISCSI.md says what the service does: its limits, its port, and that a file is never replaced."""
    from backend.services import iscsi_target as it

    text = _doc("ISCSI.md")
    assert f"from {it.MIN_GB} to {it.MAX_GB}" in text and f"Up to {it.MAX_DISKS} disks" in text
    assert f"port {it.PORT}" in text and it.PORT == 3260
    assert "12 to 16 characters without spaces" in text and it.SECRET.pattern.endswith("{12,16}$")
    assert f"ends in `{it.FILE_SUFFIX}`" in text and it.IQN_PREFIX in text
    assert "never replaces a file that is already there" in text and "never smaller" in text
    assert f"(`{it.CONTAINER}`)" in text and "has no special rights" in text
