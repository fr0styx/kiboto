"""SET-25 Apps decision 1: "Show Docker details" is one of the person's own preferences."""

from backend.api.auth import MyPreferences


def test_apps_details_is_a_preference():
    assert MyPreferences(apps_details=True).model_dump()["apps_details"] is True
    assert MyPreferences().apps_details is None  # not sent: not changed
