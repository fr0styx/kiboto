"""On a machine set up for Kiboto the system disk holds no shared folders (system_disk.py)."""

import os
from unittest.mock import MagicMock, patch

import pytest

from backend import runtime
from backend.errors import SaidError
from backend.hardware.hal import DiskDiscoveryHAL
from backend.hardware.pal import pool_registry, system_disk
from backend.hardware.pal.base import NetworkShare
from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter
from backend.services import samba_engine


@pytest.fixture
def box(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    main = tmp_path / "storage"
    main.mkdir()
    rows, mounted = [], set()
    monkeypatch.setattr(pool_registry, "load", lambda: [dict(r) for r in rows])
    real_ismount = os.path.ismount
    monkeypatch.setattr(os.path, "ismount", lambda p: str(p) in mounted or real_ismount(p))
    monkeypatch.setattr(samba_engine, "_allowed_share_roots", lambda: [str(main)])

    def pool(name, here=True, ejected=False):
        mp = main / name
        mp.mkdir(exist_ok=True)
        rows.append({"name": name, "mountpoint": str(mp), "ejected": ejected})
        if here:
            mounted.add(str(mp))
        return str(mp)

    return type("Box", (), {"main": str(main), "pool": staticmethod(pool), "rows": rows, "mounted": mounted})


def test_a_folder_is_on_the_system_disk_unless_it_is_on_a_pool(box):
    tank = box.pool("tank")
    away = box.pool("away", here=False)
    box.pool("out", ejected=True)
    assert system_disk.on_it(os.path.join(box.main, "shares")) is True
    assert system_disk.on_it(os.path.join(box.main, "out", "x")) is True  # ejected: not one of its pools
    assert system_disk.on_it(os.path.join(tank, "photos")) is False
    assert system_disk.on_it(tank) is False
    assert system_disk.on_it(os.path.join(away, "films")) is False  # away, still that pool's folder
    assert system_disk.on_it(box.main + "-other") is True  # a name that only starts like a pool's
    assert system_disk.new_share_problem(box.main) == system_disk.ON_SYSTEM_DISK
    assert system_disk.new_share_problem(tank) is None


def test_elsewhere_the_host_decides(box, monkeypatch):
    monkeypatch.setattr(runtime, "MANAGED_MARK", os.path.join(box.main, "no-mark"))
    assert system_disk.applies() is False and system_disk.on_it(box.main) is False
    adapter = GenericLinuxStorageAdapter(pool_path=box.main)
    assert adapter._default_share_folder("music") == os.path.join(box.main, "music")
    assert system_disk.default_share_after_pool(adapter, have_shares=False) == ""


def test_a_new_share_goes_on_the_first_pool(box):
    adapter = GenericLinuxStorageAdapter(pool_path=box.main)
    with pytest.raises(SaidError, match="Make a storage pool first"):
        adapter._default_share_folder("music")
    box.pool("away", here=False)
    tank = box.pool("tank")
    box.pool("media")
    assert system_disk.first_pool() == tank
    assert adapter._default_share_folder("music") == os.path.join(tank, "music")
    with pytest.raises(SaidError, match="no shared folders on the system disk"):
        adapter._not_on_the_system_disk(os.path.join(box.main, "music"))
    assert adapter._not_on_the_system_disk(os.path.join(tank, "music")) == os.path.join(tank, "music")
    with pytest.raises(SaidError) as e:
        adapter.create_share(name="music", path=os.path.join(box.main, "music"))
    assert e.value.text["msg_key"] == "srv.share_system_disk"


def test_old_shares_on_the_system_disk_say_so(box):
    tank = box.pool("tank")
    old = NetworkShare(name="storage", mountpoint=os.path.join(box.main, "shares"))
    new = NetworkShare(name="photos", mountpoint=os.path.join(tank, "photos"))
    GenericLinuxStorageAdapter._mark_away([old, new])
    assert old.on_system_disk is True and new.on_system_disk is False
    box.rows.clear()  # no pool at all yet: still said
    GenericLinuxStorageAdapter._mark_away([old])
    assert old.on_system_disk is True and old.pool_away == ""


def test_the_system_disk_is_not_listed_as_a_pool(box):
    adapter = GenericLinuxStorageAdapter(pool_path=box.main)
    with (
        patch.object(adapter, "_run_cmd", return_value=(0, "", "")),
        patch.object(adapter, "_parse_mounts", return_value=[]),
        patch.object(adapter, "_is_os_overlay_or_emmc", return_value=False),
        patch("shutil.disk_usage", return_value=MagicMock(total=10**9, used=10**8, free=9 * 10**8)),
        patch.object(DiskDiscoveryHAL, "discover_physical_disks", return_value=[]),
    ):
        assert not any(p.id == "default_pool" for p in adapter.list_pools())
        box.mounted.add(box.main)  # a disk mounted at the main storage folder itself is storage
        assert any(p.id == "default_pool" for p in adapter.list_pools())


def test_the_first_pool_gets_the_first_share(box):
    made = []
    adapter = MagicMock()
    adapter.create_share.side_effect = lambda **k: made.append(k)
    assert system_disk.default_share_after_pool(adapter, have_shares=False) == ""  # no pool yet
    box.pool("tank")
    assert system_disk.default_share_after_pool(adapter, have_shares=True) == ""
    assert system_disk.default_share_after_pool(adapter, have_shares=False) == "storage"
    assert made == [{"name": "storage", "path": "", "comment": "Kiboto storage", "security": "private"}]


def test_samba_makes_no_default_share_on_a_managed_host(box, tmp_path, monkeypatch):
    monkeypatch.setattr(samba_engine, "SAMBA_SHARES_FILE", str(tmp_path / "shares.json"))
    engine = samba_engine.SambaEngine.__new__(samba_engine.SambaEngine)
    engine._shares = {}
    engine._load_shares()
    assert engine._shares == {}


def test_the_routes(box, client, auth_headers, monkeypatch):
    from backend.api import storage

    monkeypatch.setattr(samba_engine, "validate_share", lambda share: None)
    r = client.post(
        "/api/samba/shares", headers=auth_headers, json={"name": "loose", "path": os.path.join(box.main, "loose")}
    )
    assert r.status_code == 400 and "system disk" in r.json()["detail"]
    assert client.get("/api/storage/pools", headers=auth_headers).json()["system_disk_kept_free"] is True
    calls = []
    monkeypatch.setattr(system_disk, "default_share_after_pool", lambda adapter, have: calls.append(have) or "storage")
    storage._first_share_on_the_pool(object())
    assert len(calls) == 1

    def broken(adapter, have):
        raise SaidError(*system_disk.NO_POOL)

    monkeypatch.setattr(system_disk, "default_share_after_pool", broken)
    storage._first_share_on_the_pool(object())  # said in the log, the new pool stays


def test_the_system_disk_space(box, monkeypatch):
    assert set(system_disk.usage()) == {"total_bytes", "free_bytes"}

    def gone(path):
        raise OSError("no")

    monkeypatch.setattr(system_disk.shutil, "disk_usage", gone)
    assert system_disk.usage() == {}
