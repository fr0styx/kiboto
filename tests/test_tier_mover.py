"""The program that moves a tiering run's files (19 Nov 2026). Whatever stops a file from moving
must leave it where it was, whole. Tried too in a throwaway container with exactly the rights
Kiboto gives it, on files that belong to someone else."""

import errno
import json
import os
import shutil

import pytest

from backend.services import tier_mover as tm


@pytest.fixture
def sides(tmp_path):
    fast, slow = tmp_path / "fast", tmp_path / "slow"
    fast.mkdir()
    slow.mkdir()
    return fast, slow


def _put(root, rel, text="hello", mode=0o640, mtime=1_600_000_000):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.chmod(path, mode)
    os.utime(path, (mtime, mtime))
    return path


def test_a_file_moves_whole_with_its_folders_mode_and_date(sides):
    fast, slow = sides
    _put(fast, "Films/2019/a.mkv", "a" * 5000)
    os.chmod(fast / "Films" / "2019", 0o750)
    assert tm.move_one(str(fast), str(slow), "Films/2019/a.mkv") == ("moved", 5000)
    moved = slow / "Films" / "2019" / "a.mkv"
    assert moved.read_text() == "a" * 5000 and not (fast / "Films" / "2019" / "a.mkv").exists()
    st = os.stat(moved)
    assert oct(st.st_mode & 0o777) == "0o640" and int(st.st_mtime) == 1_600_000_000
    assert oct(os.stat(slow / "Films" / "2019").st_mode & 0o777) == "0o750"
    assert os.listdir(slow / "Films" / "2019") == ["a.mkv"]  # no half-written copy left beside it
    assert (fast / "Films" / "2019").is_dir()  # the folder itself stays


def test_what_must_not_move_stays(sides, monkeypatch):
    fast, slow = sides
    _put(fast, "twice.txt")
    os.link(fast / "twice.txt", fast / "second-name.txt")
    os.symlink(fast / "twice.txt", fast / "link.txt")
    _put(fast, "there.txt", "fast one")
    _put(slow, "there.txt", "slow one")
    _put(fast, "open.txt")
    monkeypatch.setattr(tm, "in_use", lambda path: path.endswith("open.txt"))
    assert tm.move_one(str(fast), str(slow), "twice.txt") == ("not_plain", 0)
    assert tm.move_one(str(fast), str(slow), "link.txt") == ("not_plain", 0)
    assert tm.move_one(str(fast), str(slow), "there.txt") == ("already_there", 0)
    assert (slow / "there.txt").read_text() == "slow one" and (fast / "there.txt").read_text() == "fast one"
    assert tm.move_one(str(fast), str(slow), "open.txt") == ("in_use", 0)
    assert tm.move_one(str(fast), str(slow), "never-was.txt") == ("gone", 0)
    assert tm.move_one(str(fast), str(slow), "../slow/there.txt") == ("outside", 0)
    assert sorted(os.listdir(slow)) == ["there.txt"]


def test_a_folder_that_leads_out_of_the_fast_side_is_not_followed(sides, tmp_path):
    fast, slow = sides
    elsewhere = tmp_path / "elsewhere"
    _put(elsewhere, "secret.txt")
    os.symlink(elsewhere, fast / "way-out")
    assert tm.move_one(str(fast), str(slow), "way-out/secret.txt") == ("outside", 0)
    assert (elsewhere / "secret.txt").exists() and os.listdir(slow) == []


def test_a_file_written_to_while_it_was_copied_stays(sides, monkeypatch):
    fast, slow = sides
    src = _put(fast, "busy.txt", "before")
    real = shutil.copyfileobj

    def copy_then_someone_writes(fin, fout, length=0):
        real(fin, fout, length)
        src.write_text("before and more")

    monkeypatch.setattr(tm.shutil, "copyfileobj", copy_then_someone_writes)
    assert tm.move_one(str(fast), str(slow), "busy.txt") == ("changed", 0)
    assert src.read_text() == "before and more" and os.listdir(slow) == []


def test_no_room_or_a_failed_write_leaves_nothing_behind(sides, monkeypatch):
    fast, slow = sides
    _put(fast, "big.bin", "x" * 1000)
    room = os.statvfs(str(slow))

    class Full:
        f_bavail, f_frsize = 10, room.f_frsize

    with monkeypatch.context() as m:
        m.setattr(tm.os, "statvfs", lambda path: Full)
        assert tm.move_one(str(fast), str(slow), "big.bin") == ("no_room", 0)

    def fails(fin, fout, length=0):
        fout.write(b"half")
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(tm.shutil, "copyfileobj", fails)
    with pytest.raises(OSError):
        tm.move_one(str(fast), str(slow), "big.bin")
    assert (fast / "big.bin").read_text() == "x" * 1000 and os.listdir(slow) == []


def test_a_run_counts_each_outcome_and_goes_on_after_an_error(sides, monkeypatch):
    fast, slow = sides
    for name in ("a.txt", "b.txt", "c.txt"):
        _put(fast, name, name)
    real = tm.move_one

    def one(fast_root, slow_root, rel, keep_free=0):
        if rel == "b.txt":
            raise OSError(errno.EIO, "Input/output error")
        return real(fast_root, slow_root, rel, keep_free)

    monkeypatch.setattr(tm, "move_one", one)
    out = tm.run({"fast": str(fast), "slow": str(slow), "files": ["a.txt", "b.txt", "c.txt", "gone.txt"]})
    assert out["moved"] == ["a.txt", "c.txt"] and out["bytes"] == 10 and out["stopped"] == ""
    assert out["counts"] == {"moved": 2, "error": 1, "gone": 1}
    assert out["errors"] == [{"file": "b.txt", "why": "Input/output error"}]


def test_a_full_slow_side_ends_the_run_without_touching_the_rest(sides, monkeypatch):
    fast, slow = sides
    for name in ("a.txt", "b.txt", "c.txt"):
        _put(fast, name)
    tried = []

    def one(fast_root, slow_root, rel, keep_free=0):
        tried.append(rel)
        if rel == "b.txt":
            raise OSError(errno.ENOSPC, "No space left on device")
        return "moved", 5

    monkeypatch.setattr(tm, "move_one", one)
    out = tm.run({"fast": str(fast), "slow": str(slow), "files": ["a.txt", "b.txt", "c.txt"]})
    assert tried == ["a.txt", "b.txt"] and out["stopped"] == "full" and out["counts"] == {"moved": 1, "no_room": 1}


def test_asked_to_stop_the_file_in_hand_stays_and_the_result_is_still_written(sides, monkeypatch, tmp_path):
    fast, slow = sides
    _put(fast, "a.txt", "aaa")
    _put(fast, "b.txt", "bbb")

    def stopped_midway(fin, fout, length=0):
        fout.write(b"half")
        if fin.name.endswith("b.txt"):
            tm._stop(15, None)
        fout.seek(0)
        fout.truncate()
        fout.write(fin.read())

    monkeypatch.setattr(tm.shutil, "copyfileobj", stopped_midway)
    monkeypatch.setattr(tm.signal, "signal", lambda *a: None)  # the test run keeps its own handling
    job = tmp_path / "job"
    job.mkdir()
    (job / "job.json").write_text(json.dumps({"fast": str(fast), "slow": str(slow), "files": ["a.txt", "b.txt"]}))
    assert tm.main(["tier_mover", str(job / "job.json")]) == 0
    out = json.loads((job / "result.json").read_text())
    assert out["moved"] == ["a.txt"] and out["stopped"] == "asked"
    assert (fast / "b.txt").read_text() == "bbb" and os.listdir(slow) == ["a.txt"]


def test_in_use_says_no_for_a_file_nobody_has_open(sides):
    fast, _slow = sides
    path = _put(fast, "idle.txt")
    assert tm.in_use(str(path)) is False
    assert tm.in_use(str(fast / "never-was.txt")) is True  # cannot be opened: not to be moved


def test_the_free_space_the_share_asks_for_is_left_on_the_drive(sides, monkeypatch):
    fast, slow = sides
    _put(fast, "a.bin", "x" * 1000)
    room = os.statvfs(str(slow))
    gib = 1024**3

    class Drive:
        f_bavail, f_frsize = 5 * gib // room.f_frsize, room.f_frsize

    monkeypatch.setattr(tm.os, "statvfs", lambda path: Drive)
    job = {"fast": str(fast), "slow": str(slow), "files": ["a.bin"]}
    out = tm.run({**job, "keep_free": 6 * gib})  # the share keeps 6 GiB free; the drive has 5
    assert out["counts"] == {"no_room": 1} and out["stopped"] == "full" and (fast / "a.bin").exists()
    assert tm.run({**job, "keep_free": 4 * gib})["moved"] == ["a.bin"]
