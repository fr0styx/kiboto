"""create_user hands back the new person, or says loudly that it cannot (pyright clean-up, 19 Nov 2026)."""

from unittest.mock import patch

import pytest

from backend.users_db import create_user, init_users_db


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "users.db")
    init_users_db(path)
    return path


def test_a_missing_row_right_after_creating_is_an_error_not_none(db):
    with patch("backend.users_db.get_user_by_id", return_value=None):
        with pytest.raises(LookupError, match="missing right after it was created"):
            create_user("mia", "Mia", "Aa1-long-enough-pass", db_path=db)


def test_a_samba_failure_still_creates_the_person_and_refreshes_shares(db):
    engine = patch("backend.services.samba_engine.get_samba_engine", side_effect=OSError("no smbpasswd"))
    refresh = patch("backend.services.samba_engine.refresh_access")
    with engine, refresh as refreshed:
        user = create_user("leo", "Leo", "Aa1-long-enough-pass", db_path=db)
    assert user["username"] == "leo"
    refreshed.assert_called_once()
