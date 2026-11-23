"""A pool id names a folder of the storage folder: "../etc" or "/etc" is none of its pools."""

import pytest

from backend.hardware.pal import generic_linux, pool_registry
from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    main = tmp_path / "storage"
    (main / "tank").mkdir(parents=True)
    (tmp_path / "etc").mkdir()
    monkeypatch.setattr(pool_registry, "find", lambda pool_id: None)
    monkeypatch.setattr(generic_linux.pool_registry, "find", lambda pool_id: None)
    return GenericLinuxStorageAdapter(pool_path=str(main))


def test_a_pool_id_stays_inside_the_storage_folder(adapter, tmp_path):
    main = str(tmp_path / "storage")
    assert adapter.get_pool_path("tank") == str(tmp_path / "storage" / "tank")
    for bad in ("../etc", "../../etc", str(tmp_path / "etc"), "tank/../../etc", "..", "tank/sub", "missing"):
        assert adapter.get_pool_path(bad) == main, bad
    assert adapter.get_pool_path("default") == main


def test_snapshots_of_a_pool_id_outside_make_nothing_there(adapter, tmp_path):
    adapter.list_snapshots("../etc")
    assert not (tmp_path / "etc" / "@snapshots").exists()
