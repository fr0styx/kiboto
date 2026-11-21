"""Copying or moving a folder onto a link of the same name never writes through the link."""

import os

import pytest

from backend.services.fs_transfer import execute_transfer


@pytest.mark.parametrize("action", ["copy", "move"])
def test_a_folder_lands_beside_a_link_of_its_name(tmp_path, action):
    outside = tmp_path / "outside"
    outside.mkdir()
    src = tmp_path / "src" / "photos"
    (src / "2020").mkdir(parents=True)
    (src / "2020" / "a.jpg").write_text("a")
    dest = tmp_path / "dest"
    dest.mkdir()
    os.symlink(str(outside), str(dest / "photos"))
    res = execute_transfer([str(src)], str(dest), action=action, policy="merge")
    assert res["errors"] == []
    assert os.listdir(outside) == []  # nothing went where the link points
    assert os.path.islink(dest / "photos")
    landed = [n for n in os.listdir(dest) if n != "photos"]
    assert len(landed) == 1 and (dest / landed[0] / "2020" / "a.jpg").read_text() == "a"


def test_a_real_folder_is_still_merged(tmp_path):
    src = tmp_path / "src" / "photos"
    src.mkdir(parents=True)
    (src / "b.jpg").write_text("b")
    dest = tmp_path / "dest"
    (dest / "photos").mkdir(parents=True)
    (dest / "photos" / "a.jpg").write_text("a")
    execute_transfer([str(src)], str(dest), action="copy", policy="merge")
    assert sorted(os.listdir(dest / "photos")) == ["a.jpg", "b.jpg"]
