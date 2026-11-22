"""A shared folder on a pool that is away says so, instead of showing an empty folder."""

import os

from backend.hardware.pal import pool_registry
from backend.hardware.pal.base import NetworkShare
from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter


def test_a_folder_on_a_pool_that_is_not_mounted_names_it(tmp_path, monkeypatch):
    tank, media = tmp_path / "tank", tmp_path / "media"
    (tank / "films").mkdir(parents=True)
    (media / "music").mkdir(parents=True)
    rows = [
        {"name": "tank", "mountpoint": str(tank)},
        {"name": "media", "mountpoint": str(media)},
        {"name": "x", "mountpoint": "/"},
    ]
    monkeypatch.setattr(os.path, "ismount", lambda p: p == str(media))
    assert pool_registry.away_pool_of(str(tank / "films"), rows) == "tank"
    assert pool_registry.away_pool_of(str(tank), rows) == "tank"
    assert pool_registry.away_pool_of(str(media / "music"), rows) == ""
    assert pool_registry.away_pool_of(str(tmp_path / "tankless"), rows) == ""  # a name that only starts the same
    assert pool_registry.away_pool_of("", rows) == ""
    assert pool_registry.away_pool_of("/srv/other", rows) == ""  # the root pool row never claims everything


def test_the_share_list_marks_folders_on_an_away_pool(tmp_path, monkeypatch):
    rows = [{"name": "tank", "mountpoint": str(tmp_path / "tank")}]
    monkeypatch.setattr(pool_registry, "load", lambda: rows)
    monkeypatch.setattr(os.path, "ismount", lambda p: False)
    shares = [
        NetworkShare(name="films", mountpoint=str(tmp_path / "tank" / "films")),
        NetworkShare(name="docs", mountpoint="/srv/docs"),
    ]
    marked = GenericLinuxStorageAdapter._mark_away(shares)
    assert [(s.name, s.pool_away) for s in marked] == [("films", "tank"), ("docs", "")]
    monkeypatch.setattr(pool_registry, "load", lambda: [])
    assert [s.pool_away for s in GenericLinuxStorageAdapter._mark_away([NetworkShare(name="a", mountpoint="/x")])] == [
        ""
    ]
