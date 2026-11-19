"""Data tiering (owner's decisions, 19 Nov 2026): per shared folder, off until turned on; a file is
old when it was not opened and not changed for the folder's days; a folder is watched that long
before anything moves; one way only. The move here is made by the real mover, in place of the
container Kiboto starts for it."""

import json
import os
import threading
import time

import pytest

from backend.hardware.pal.base import NetworkShare, PlatformType
from backend.services import open_watch, tier_mover
from backend.services import tiering as tr

DAY = 86400


class Platform:
    def __init__(self, kind, shares):
        self.kind, self.shares = kind, shares

    def get_platform_type(self):
        return self.kind

    def list_shares(self):
        return self.shares


def _share(name, mode, pool="ssd"):
    return NetworkShare(name=name, cache_mode=mode, cache_pool=pool)


@pytest.fixture(autouse=True)
def nas(tmp_path, monkeypatch):
    mnt, data, array = tmp_path / "mnt", tmp_path / "data", tmp_path / "array"
    for share in ("Films", "Downloads", "Games"):
        (mnt / "ssd" / share).mkdir(parents=True)
        (mnt / "user" / share).mkdir(parents=True)
    data.mkdir()
    array.mkdir()
    monkeypatch.setattr(tr, "MNT", str(mnt))
    monkeypatch.setattr(tr, "STATE_FILE", str(data / "tiering.json"))
    monkeypatch.setattr(tr, "JOBS_DIR", str(data / "tiering"))
    monkeypatch.setattr(tr, "SETTLE_SECS", 0)
    monkeypatch.setattr(open_watch, "DB_FILE", str(data / "opens.db"))
    open_watch._seen.clear()
    plat = Platform(
        PlatformType.UNRAID,
        [_share("Films", "only"), _share("Downloads", "yes"), _share("Games", "prefer"), _share("Backups", "no", None)],
    )
    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda *a, **k: plat)
    state = {"plat": plat, "mnt": mnt, "array": array, "data": data, "calls": [], "mover": None, "events": []}
    state["watching"] = {"watching": True, "folders": [str(mnt / "ssd" / "Films")], "error": ""}
    monkeypatch.setattr(open_watch, "status", lambda: state["watching"])
    monkeypatch.setattr(
        open_watch, "watch", lambda folders, roots, on_host=None: state.update(watched=(folders, on_host))
    )
    monkeypatch.setattr("backend.state.add_event", lambda *a, **k: state["events"].append(a))
    me = {
        "Config": {"Image": "ghcr.io/example/kiboto:sha-abc"},
        "Mounts": [
            {"Source": "/host/ssd", "Destination": str(mnt / "ssd")},
            {"Source": "/host/appdata/kiboto", "Destination": str(data)},
        ],
    }
    here = {"/host/ssd": str(mnt / "ssd"), "/host/appdata/kiboto": str(data), "/mnt/user0": str(array)}

    def local(host_path):
        for outside, inside in here.items():
            if host_path.startswith(outside):
                return inside + host_path[len(outside) :]
        raise AssertionError(host_path)

    def docker(method, path, body=None, headers=None):
        state["calls"].append((method, path, body, headers))
        if state.get("no_engine"):
            return 0, None
        if method == "GET" and path.endswith(f"/{tr.CONTAINER}/json"):
            return (200, {"State": {"Running": state["mover"] == "running"}}) if state["mover"] else (404, None)
        if method == "GET":
            return 200, me
        if method == "POST" and "/create" in path:
            state["mover"], state["made"] = "created", body
            return 201, {}
        if method == "POST" and path.endswith("/start"):
            binds = {b.rsplit(":", 1)[1]: local(b.rsplit(":", 1)[0]) for b in state["made"]["HostConfig"]["Binds"]}
            os.makedirs(binds["/slow"], exist_ok=True)  # Docker makes a folder that is not there yet
            with open(os.path.join(binds["/job"], "job.json"), encoding="utf-8") as f:
                job = json.load(f)
            assert (job["fast"], job["slow"]) == ("/fast", "/slow")
            out = tier_mover.run({"fast": binds["/fast"], "slow": binds["/slow"], "files": job["files"]})
            with open(os.path.join(binds["/job"], "result.json"), "w", encoding="utf-8") as f:
                json.dump(out, f)
            state["mover"] = "ended"
            return 204, {}
        if method == "DELETE":
            state["mover"] = None
        return 204, {}

    monkeypatch.setattr(tr, "_docker", docker)
    tr._ran.clear()
    tr._busy.clear()
    tr._tried["watch"] = 0.0
    yield state
    open_watch._seen.clear()


def _file(nas, rel, text="data", age_days=400):
    path = nas["mnt"] / "ssd" / "Films" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    when = time.time() - age_days * DAY
    os.utime(path, (when, when))
    return str(path)


def _later(days=200):
    """A moment far enough ahead that a file made just now counts as untouched for 90 days."""
    return time.time() + days * DAY


def test_only_a_folder_that_stays_on_the_fast_pool_fits(nas):
    os.symlink(nas["mnt"] / "ssd" / "Films", nas["mnt"] / "user" / "Linked")
    (nas["mnt"] / "ssd" / "Linked").mkdir()
    nas["plat"].shares += [_share("Linked", "only"), _share("Elsewhere", "only", "nvme")]
    why = {c["name"]: c["why"] for c in tr.candidates()}
    assert why == {
        "Films": "",
        "Downloads": "unraid_moves_all",
        "Games": "unraid_moves_back",
        "Backups": "not_on_fast",
        "Linked": "exclusive",
        "Elsewhere": "fast_not_visible",
    }
    films = next(c for c in tr.candidates() if c["name"] == "Films")
    assert films["fast"] == str(nas["mnt"] / "ssd" / "Films") and films["slow_host"] == "/mnt/user0/Films"
    nas["plat"].kind = PlatformType.GENERIC_LINUX
    assert {c["why"] for c in tr.candidates()} == {"no_merged_folder"}


def test_off_until_turned_on_and_only_where_it_fits(nas):
    assert tr.folders() == [] and all(not f["enabled"] for f in tr.view()["folders"])
    tr.watch()
    assert nas["watched"] == ([], None) and not os.path.exists(open_watch.DB_FILE)  # off everywhere: no record at all
    for name, days, key in (
        ("Downloads", 90, "no_fit"),
        ("Nope", 90, "no_folder"),
        ("Films", 3, "bad_days"),
        ("Films", True, "bad_days"),
    ):
        with pytest.raises(tr.NotNow) as e:
            tr.set_folder(name, True, days)
        assert e.value.key == key
    made = tr.set_folder("Films", True, 30, now=1000.0)
    assert (made["days"], made["since"], made["last_run"]) == (30, 1000.0, None)
    again = tr.set_folder("Films", True, 60, now=5000.0)  # other days: the watching did not start over
    assert (again["id"], again["days"], again["since"]) == (made["id"], 60, 1000.0)
    open_watch.note(made["fast"] + "/a.mkv", 100)
    assert tr.set_folder("Films", False) is None and tr.folders() == []
    assert open_watch.last_opened(made["fast"]) == {}  # turned off: its record of opens is gone
    assert tr.set_folder("Films", False) is None


def test_nothing_is_chosen_while_kiboto_is_still_learning(nas):
    folder = tr.set_folder("Films", True, 90)
    _file(nas, "ancient.mkv")
    chosen = tr.select(folder, now=time.time() + 89 * DAY)
    assert chosen["learning"] is True and chosen["files"] == []
    assert tr.select(folder, now=_later())["files"] == ["ancient.mkv"]


def test_old_means_not_opened_and_not_changed_for_the_days(nas):
    folder = tr.set_folder("Films", True, 90)
    now = _later()
    today = open_watch.today(now)
    _file(nas, "2019/untouched.mkv", "x" * 10)
    _file(nas, "opened-long-ago.mkv", "x" * 5)
    watched = _file(nas, "watched-last-week.mkv")
    almost = _file(nas, "opened-89-days-ago.mkv")
    fresh = _file(nas, "changed-last-week.mkv")
    os.utime(fresh, (now - 7 * DAY, now - 7 * DAY))
    _file(nas, ".hidden")
    _file(nas, ".stuff/inside.txt")
    twin = _file(nas, "two-names.mkv")
    os.link(twin, twin + ".second")
    os.symlink(watched, str(nas["mnt"] / "ssd" / "Films" / "a-link.mkv"))
    open_watch.note(folder["fast"] + "/opened-long-ago.mkv", today - 90)
    open_watch.note(watched, today - 7)
    open_watch.note(almost, today - 89)
    chosen = tr.select(folder, now=now)
    assert chosen["files"] == ["opened-long-ago.mkv", "2019/untouched.mkv"] and chosen["bytes"] == 15
    assert chosen["more"] is False and chosen["why"] == ""
    capped = tr.select(folder, now=now, limit=1)
    assert capped["files"] == ["opened-long-ago.mkv"] and capped["more"] is True


def test_nothing_is_chosen_when_kiboto_is_not_listening(nas):
    folder = tr.set_folder("Films", True, 90)
    _file(nas, "ancient.mkv")
    for status in (
        {"watching": False, "folders": [], "error": "x"},
        {"watching": True, "folders": ["/mnt/other"], "error": ""},
    ):
        nas["watching"] = status
        chosen = tr.select(folder, now=_later())
        assert chosen["files"] == [] and chosen["why"] == "not_watching"


def test_a_run_moves_the_old_files_in_a_container_that_sees_only_the_folder(nas):
    folder = tr.set_folder("Films", True, 90)
    now = _later()
    old, kept = _file(nas, "2019/old.mkv", "o" * 100), _file(nas, "new.mkv")
    os.utime(kept, (now, now))
    open_watch.note(old, open_watch.today(now) - 200)
    out = tr.run("Films", "hand", now)
    assert (out["moved"], out["bytes"], out["chosen"], out["why"], out["errors"]) == (1, 100, 1, "", [])
    assert (nas["array"] / "Films" / "2019" / "old.mkv").read_text() == "o" * 100
    assert not os.path.exists(old) and os.path.exists(kept)
    made = nas["made"]
    assert made["Image"] == "ghcr.io/example/kiboto:sha-abc" and made["Cmd"] == [tr.MOVER, "/job/job.json"]
    host = made["HostConfig"]
    assert host["NetworkMode"] == "none" and host["CapDrop"] == ["ALL"] and "SYS_ADMIN" not in host["CapAdd"]
    assert host["Binds"] == [
        "/host/ssd/Films:/fast",
        "/mnt/user0/Films:/slow",
        f"/host/appdata/kiboto/tiering/{folder['id']}:/job",
    ]
    assert nas["mover"] is None and not os.path.exists(os.path.join(tr.JOBS_DIR, folder["id"]))  # tidied up
    assert open_watch.last_opened(folder["fast"]) == {}  # the moved file's opens are no longer kept
    assert tr.get("Films")["last_run"]["moved"] == 1 and tr.view()["folders"][0]["last_run"]["how"] == "hand"
    assert [e[0] for e in nas["events"]] == ["info"]


def test_a_file_the_mover_left_does_not_count_as_opened_today(nas, monkeypatch):
    folder = tr.set_folder("Films", True, 90)
    now = _later()
    stays = _file(nas, "there-already.mkv")
    (nas["array"] / "Films").mkdir()
    (nas["array"] / "Films" / "there-already.mkv").write_text("the slow pool's own")
    real = tier_mover.run

    def looked_at(job):
        open_watch.note(stays)  # the mover looking at the file is seen as an open
        return real(job)

    monkeypatch.setattr(tier_mover, "run", looked_at)
    out = tr.run("Films", "schedule", now)
    assert out["moved"] == 0 and out["counts"] == {"already_there": 1}
    assert open_watch.last_opened(folder["fast"]) == {} and os.path.exists(stays)
    assert nas["events"] == []  # nothing moved, nothing went wrong: no entry in the log


def test_a_run_that_cannot_start_says_why_and_moves_nothing(nas):
    tr.set_folder("Films", True, 90)
    old = _file(nas, "old.mkv")
    nas["no_engine"] = True
    out = tr.run("Films", "schedule", _later())
    assert (out["why"], out["moved"], out["chosen"]) == ("no_engine", 0, 1) and os.path.exists(old)
    assert [e[0] for e in nas["events"]] == ["warning"]
    with pytest.raises(tr.NotNow) as e:
        tr.run("Downloads")
    assert e.value.key == "no_folder"


def test_one_run_at_a_time_also_after_a_restart(nas):
    tr.set_folder("Films", True, 90)
    nas["mover"] = "running"  # a mover from before Kiboto restarted is still at work
    with pytest.raises(tr.NotNow) as e:
        tr.run("Films")
    assert e.value.key == "busy" and not tr._busy
    assert not [c for c in nas["calls"] if c[0] == "DELETE"]  # and it was left alone
    nas["mover"] = None
    tr._busy.add("someone")
    with pytest.raises(tr.NotNow) as e:
        tr.run_soon("Films")
    assert e.value.key == "busy"


def test_the_night_run_starts_once_a_day_at_its_time(nas, monkeypatch):
    tr.set_folder("Films", True, 90)
    ran = []
    monkeypatch.setattr(tr, "run", lambda name, how, now=None: ran.append((name, how)))
    at = time.mktime((2026, 11, 20, 3, 0, 5, 0, 0, -1))
    assert tr.run_due(at - 120) == [] and tr.run_due(at) == ["Films"] and tr.run_due(at + 20) == []
    for t in threading.enumerate():
        if t.name == "tiering-night":
            t.join(5)
    assert ran == [("Films", "schedule")]
    assert tr.run_due(at + DAY) == ["Films"]


def test_a_listener_that_ended_is_started_again(nas, monkeypatch):
    tr.set_folder("Films", True, 90)
    started = []
    monkeypatch.setattr(tr, "watch_soon", lambda: started.append(1))
    nas["watching"] = {"watching": False, "folders": [], "error": ""}
    tr.run_due(10_000.0)
    tr.run_due(10_060.0)  # not every minute
    tr.run_due(10_000.0 + tr.RETRY_WATCH_SECS)
    assert started == [1, 1]


def test_after_a_long_time_without_listening_the_folders_are_learned_again(nas, monkeypatch):
    made = tr.set_folder("Films", True, 90, now=1000.0)
    monkeypatch.setattr(tr, "_booted", lambda: 500.0)
    tr.watch(now=2000.0)  # never listened before: nothing was missed
    assert tr.get("Films")["since"] == 1000.0 and nas["watched"][0] == [made["fast"]]
    assert nas["watched"][1] == {made["fast"]: "/host/ssd/Films"}  # opens from outside carry the host's path
    open_watch.mark_alive(5000.0)
    tr.watch(now=5000.0 + tr.MAX_UNWATCHED_SECS - 1)
    assert tr.get("Films")["since"] == 1000.0 and nas["events"] == []
    monkeypatch.setattr(tr, "_booted", lambda: 90_000.0)  # the NAS itself was off for most of the gap
    tr.watch(now=90_600.0)
    assert tr.get("Films")["since"] == 1000.0
    monkeypatch.setattr(tr, "_booted", lambda: 500.0)  # it ran, and Kiboto did not listen
    tr.watch(now=90_600.0)
    assert tr.get("Films")["since"] == 90_600.0 and [e[0] for e in nas["events"]] == ["warning"]
    assert tr.select(tr.get("Films"), now=90_600.0 + 89 * DAY)["learning"] is True


def test_the_screen_is_told_how_each_folder_stands(nas):
    tr.set_folder("Films", True, 45, now=1000.0)
    view = tr.view(now=1000.0 + 10 * DAY)
    films = view["folders"][0]
    assert films == {
        "name": "Films",
        "why": "",
        "enabled": True,
        "days": 45,
        "since": 1000.0,
        "learning_until": 1000.0 + 45 * DAY,
        "learning": True,
        "last_run": None,
        "watching": True,
    }
    assert view["folders"][1] == {"name": "Downloads", "why": "unraid_moves_all", "enabled": False}
    assert (view["run_at"], view["default_days"], view["moving"], view["watch_error"]) == ("03:00", 90, False, "")
