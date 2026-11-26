"""Merged folders on Kiboto OS (ADR 0006): the host door merges, mounts, moves and listens, from
its own record and with every path checked; Kiboto's web process keeps a copy for the page."""

import json
import os
from types import SimpleNamespace

import pytest

from backend import door, runtime
from backend.services import host_basics, open_watch, tier_merge, tiering


@pytest.fixture
def kiboto_os(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    monkeypatch.setattr(runtime, "is_root", lambda: False)
    monkeypatch.setattr(tier_merge.merged_folders, "STATE_FILE", str(tmp_path / "web-merges.json"))


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """A storage folder with a fast pool (a shared folder in it) and a slow one, Kiboto's own data
    folder beside them, and the door's own record in a folder of its own."""
    from backend import config

    root = tmp_path / "storage"
    (root / "fast" / "films").mkdir(parents=True)
    (root / "slow").mkdir()
    monkeypatch.setattr(config, "POOL_PATH", str(root))
    monkeypatch.setattr(tier_merge, "DATA_DIR", str(root / "fast" / "kiboto"))
    monkeypatch.setattr(tier_merge, "DOOR_DIR", str(tmp_path / "door"))
    pools = [
        SimpleNamespace(id="fast", mountpoint=str(root / "fast")),
        SimpleNamespace(id="slow", mountpoint=str(root / "slow")),
    ]
    from backend.hardware import pal_storage

    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: SimpleNamespace(list_pools=lambda: pools))
    return root


MERGE = {
    "name": "films",
    "path": "/s/fast/films",
    "fast": "/s/fast/.kiboto-tier/films",
    "slow": "/s/slow/.kiboto-tier/films",
}


def test_on_kiboto_os_the_door_merges_and_kiboto_keeps_a_copy(kiboto_os, monkeypatch):
    asked = []
    monkeypatch.setattr(door, "via", lambda op, here, **kw: asked.append((op, kw)) or dict(MERGE))
    made = tier_merge.add("films", "/s/fast/films/", "/s/slow", "slow")
    assert asked == [
        ("merge.add", {"name": "films", "path": "/s/fast/films", "slow_mount": "/s/slow", "slow_pool": "slow"})
    ]
    assert made == MERGE and tier_merge.of("/s/fast/films") == MERGE  # the page and snapshots see it
    monkeypatch.setattr(door, "via", lambda op, here, **kw: {"error": "no_tool", "message": "no mergerfs"})
    with pytest.raises(tier_merge.MergeError) as e:
        tier_merge.add("music", "/s/fast/music", "/s/slow", "slow")
    assert e.value.key == "no_tool"
    monkeypatch.setattr(door, "via", lambda op, here, **kw: asked.append((op, kw)) or True)
    assert tier_merge.remove_if_empty("/s/fast/films") is True
    assert asked[-1] == ("merge.remove", {"path": "/s/fast/films"}) and tier_merge.of("/s/fast/films") is None
    monkeypatch.setattr(door, "via", lambda op, here, **kw: asked.append((op, kw)) or "")
    assert tier_merge.ensure() == "" and asked[-1] == ("merge.ensure", {})
    monkeypatch.setattr(door, "via", lambda op, here, **kw: False)
    tier_merge._keep(dict(MERGE), True)
    assert tier_merge.remove_if_empty("/s/fast/films") is False and tier_merge.of("/s/fast/films")  # kept


def test_the_door_merges_only_a_shared_folder_onto_one_of_its_pools(storage, monkeypatch):
    done = []
    monkeypatch.setattr(tier_merge, "add", lambda *a, **k: done.append((a, k)) or {"path": a[1]})
    films = str(storage / "fast" / "films")
    assert tier_merge.add_here("films", films, str(storage / "slow"), "slow") == {"path": films}
    assert done[-1][1] == {"where": tier_merge.DOOR_DIR}  # recorded in the door's own record
    (storage / "fast" / "link").symlink_to(storage / "fast" / "films")
    (storage / "fast" / "kiboto").mkdir()
    for path in (
        str(storage / "fast" / "link"),
        str(storage / "fast"),
        "/etc",
        "films",
        str(storage / "fast" / "kiboto"),
    ):
        with pytest.raises(ValueError):
            tier_merge.add_here("films", path, str(storage / "slow"), "slow")
    for slow, pool in ((str(storage / "slow"), "fast"), ("/tmp", "slow"), ("", "slow")):
        with pytest.raises(ValueError):
            tier_merge.add_here("films", films, slow, pool)
    with pytest.raises(ValueError):
        tier_merge.add_here("../films", films, str(storage / "slow"), "slow")
    monkeypatch.setattr(tier_merge, "add", lambda *a, **k: (_ for _ in ()).throw(tier_merge.MergeError("no_tool", "x")))
    assert tier_merge.add_here("films", films, str(storage / "slow"), "slow") == {"error": "no_tool", "message": "x"}


def test_the_door_keeps_its_own_record(storage):
    tier_merge._keep(dict(MERGE), True, tier_merge.DOOR_DIR)
    assert tier_merge.door_merges() == [MERGE] and tier_merge.merges() == []  # Kiboto's copy is apart
    assert tier_merge._of("/s/fast/films", tier_merge.DOOR_DIR) == MERGE
    assert tier_merge.remove_here("/s/fast/other") is True  # never merged by the door: nothing to undo
    tier_merge._keep(dict(MERGE), False, tier_merge.DOOR_DIR)
    assert tier_merge.door_merges() == []


def test_the_door_moves_files_only_for_a_folder_it_merged(storage, monkeypatch, tmp_path):
    monkeypatch.setattr(tiering, "MOVE_DIR", str(tmp_path / "move"))
    tier_merge._keep(dict(MERGE), True, tier_merge.DOOR_DIR)
    ran = []

    def run(cmd, **kw):
        ran.append(cmd)
        job = json.loads((tmp_path / "move" / "job.json").read_text())
        (tmp_path / "move" / "result.json").write_text(json.dumps({"moved": job["files"], "bytes": 3}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", run)
    done = tiering.move_here(MERGE["fast"], MERGE["slow"], 64, ["a/b.mkv"])
    assert done == {"moved": ["a/b.mkv"], "bytes": 3} and ran[0][-1].endswith("job.json")
    for files in (["../x"], ["/etc/shadow"], ["a/../../x"], [3], "a"):
        with pytest.raises(ValueError):
            tiering.move_here(MERGE["fast"], MERGE["slow"], 64, files)
    with pytest.raises(ValueError):
        tiering.move_here(MERGE["fast"], "/s/slow/elsewhere", 64, ["a"])
    with pytest.raises(ValueError):
        tiering.move_here(MERGE["fast"], MERGE["slow"], True, ["a"])


def test_on_kiboto_os_the_mover_and_the_listener_go_through_the_door(kiboto_os, monkeypatch, tmp_path):
    asked = []
    monkeypatch.setattr(door, "via", lambda op, here, **kw: asked.append((op, kw)) or {"moved": ["a"], "why": ""})
    folder = {"name": "films", "fast": "/s/fast/.kiboto-tier/films", "id": "f1"}
    assert tiering._hand_to_mover(folder, str(tmp_path / "job"), ["a"], ("/s/slow/.kiboto-tier/films", 64)) == ""
    assert asked[-1][0] == "tier.move" and asked[-1][1]["keep_free"] == 64
    assert json.loads((tmp_path / "job" / "result.json").read_text())["moved"] == ["a"]
    monkeypatch.setattr(door, "via", lambda op, here, **kw: (_ for _ in ()).throw(ValueError("refused")))
    assert tiering._hand_to_mover(folder, str(tmp_path / "job"), ["a"], ("/x", 1)) == "no_start"
    fast = tmp_path / "fast"
    fast.mkdir()
    monkeypatch.setattr(tiering, "folders", lambda: [{"fast": str(fast), "days": 90}])
    monkeypatch.setattr(tiering, "unwatched_secs", lambda now: 0)
    monkeypatch.setattr(door, "via", lambda op, here, **kw: asked.append((op, kw)) or True)
    tiering.watch()
    assert asked[-1] == ("opens.watch", {"folders": [str(fast)]})


def test_the_listener_runs_as_kibotos_user_with_two_rights_only(storage, monkeypatch):
    seen = []
    monkeypatch.setattr(host_basics, "run", lambda cmd, timeout=30: seen.append(cmd) or (0, ""))
    films = str(storage / "fast" / "films")
    assert open_watch.watch_here([films]) is True
    started = seen[-1]
    assert started[0] == "systemd-run" and "User=kiboto" in started and started[-2:] == ["serve", films]
    assert "AmbientCapabilities=CAP_SYS_ADMIN CAP_DAC_READ_SEARCH" in started
    assert os.path.isdir(os.path.join(started[started.index("--working-directory") + 1], "backend"))
    assert open_watch.watch_here([]) is True and seen[-1][:2] == ["systemctl", "reset-failed"]  # stopped only
    for bad in (["/etc"], ["relative"], "x", [str(storage / "fast" / "nothing")]):
        with pytest.raises(ValueError):
            open_watch.watch_here(bad)


def test_an_open_by_kibotos_own_user_does_not_count(kiboto_os, monkeypatch):
    assert open_watch.outside_kiboto(os.getpid()) is False  # this process: Kiboto's own user
    assert open_watch.outside_kiboto(2**31 - 1) is True  # gone already: someone opened it
    assert open_watch.in_container(0) is True and open_watch.in_container(42) is False
    monkeypatch.setattr(open_watch, "last_alive", lambda: __import__("time").time() - 10)
    assert open_watch.status()["watching"] is True  # the machine's listener marked itself alive
    monkeypatch.setattr(open_watch, "last_alive", lambda: None)
    assert open_watch.status()["watching"] is False


def test_the_door_has_the_merge_operations():
    from backend.services import host_door

    ops = host_door.OPERATIONS
    assert ops["merge.add"].args == {"name": (str,), "path": (str,), "slow_mount": (str,), "slow_pool": (str,)}
    assert ops["merge.remove"].args == {"path": (str,)} and ops["merge.ensure"].args == {}
    assert ops["tier.move"].args == {"fast": (str,), "slow": (str,), "keep_free": (int,), "files": (list,)}
    assert ops["opens.watch"].args == {"folders": (list,)}
    assert door.LONG["tier.move"] > tiering.RUN_LIMIT_SECS
