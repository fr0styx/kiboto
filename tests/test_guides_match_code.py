"""The household guides quote numbers from the code; when a number changes, the guide must too."""

import os

from backend.services import compose_apply, docker_updates, offsite_backup

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
