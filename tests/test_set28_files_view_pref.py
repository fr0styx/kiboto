"""SET-28 Files 4: the File Explorer's view is one of the person's own preferences."""

import pytest
from pydantic import ValidationError

from backend.api.auth import FilesView, MyPreferences


def test_the_files_view_is_a_preference():
    p = MyPreferences(files={"view": "icon", "sort": "mtime", "sort_dir": "desc", "hidden": True})
    assert p.model_dump()["files"] == {"view": "icon", "sort": "mtime", "sort_dir": "desc", "hidden": True}
    assert FilesView().model_dump() == {"view": "list", "sort": "name", "sort_dir": "asc", "hidden": False}
    assert MyPreferences().files is None  # not sent: not changed


def test_only_known_values():
    with pytest.raises(ValidationError):
        FilesView(view="giant")
    with pytest.raises(ValidationError):
        FilesView(sort="colour")
