"""On a machine Kiboto runs, bringing the pools back at start and restarting Kiboto are root's work and
go through the host door (the OS audit's drill: after a restore from the pools neither worked as the
web user)."""

from backend import door, runtime
from backend.hardware.pal import pool_registry
from backend.services import host_basics, host_door


def test_the_door_has_both_operations():
    assert host_door.OPERATIONS["pools.bring_back"].args == {}
    assert host_door.OPERATIONS["kiboto.restart"].args == {"delay": (int,)}


def test_start_brings_the_pools_back_through_the_door(monkeypatch):
    from backend import main

    asked = []
    monkeypatch.setattr(pool_registry, "load", lambda: [{"name": "tank"}])
    monkeypatch.setattr(door, "via", lambda op, here, **a: asked.append((op, here)) or {})
    main._bring_pools_back()
    from backend.services import pools_at_boot

    assert asked == [("pools.bring_back", pools_at_boot.bring_back)]


def test_no_records_no_question(monkeypatch):
    from backend.services import pools_at_boot

    monkeypatch.setattr(pool_registry, "load", lambda: [])
    assert pools_at_boot.bring_back() == {}


def test_restart_goes_through_the_door_and_the_delay_is_bounded(monkeypatch):
    asked, ran = [], []
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    monkeypatch.setattr(door, "via", lambda op, here, **a: asked.append((op, a)) or True)
    assert host_basics.restart_kiboto(5) is True
    assert asked == [("kiboto.restart", {"delay": 5})]
    assert host_basics.restart_here(999, lambda cmd, **k: ran.append(cmd) or (0, "")) is True
    assert "--on-active=30" in ran[0]
    host_basics.restart_here(-4, lambda cmd, **k: ran.append(cmd) or (0, ""))
    assert "--on-active=1" in ran[1]


def test_a_guest_does_not_restart_itself(monkeypatch):
    monkeypatch.setattr(runtime, "managed_host", lambda: False)
    monkeypatch.setattr(door, "via", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked")))
    assert host_basics.restart_kiboto() is False


def test_the_adopt_mark_stays_until_every_pool_is_back(tmp_path, monkeypatch):
    import os

    monkeypatch.setattr(pool_registry, "DATA_DIR", str(tmp_path))
    flag = tmp_path / pool_registry.ADOPT_FLAG
    flag.write_text("")
    monkeypatch.setattr(pool_registry, "load", lambda: [{"name": "tank"}, {"name": "media"}])
    seen = []

    def bring_back(row, run, force=False):
        seen.append((row["name"], force))
        return "previously in use" if row["name"] == "tank" and len(seen) < 3 else ""

    monkeypatch.setattr(pool_registry, "bring_back", bring_back)
    pool_registry.bring_back_all(lambda *a: (0, "", ""))
    assert os.path.exists(flag)  # tank failed: the mark stays for the next start
    pool_registry.bring_back_all(lambda *a: (0, "", ""))
    assert seen == [("tank", True), ("media", True), ("tank", True), ("media", True)]
    assert not os.path.exists(flag)
