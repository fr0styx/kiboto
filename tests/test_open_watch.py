"""The record of which files were opened, and on which day (data tiering, 19 Nov 2026). The
listening itself was tried on a real pool in a throwaway container; here the record and the reading
of the kernel's events are checked, with events built the way the kernel writes them."""

import os

import pytest

from backend.services import open_watch as ow


@pytest.fixture(autouse=True)
def record(tmp_path, monkeypatch):
    monkeypatch.setattr(ow, "DB_FILE", str(tmp_path / "opens.db"))
    ow._seen.clear()
    yield tmp_path
    ow.stop_watching()
    ow._seen.clear()


def test_the_latest_day_of_each_file_is_kept_per_folder():
    ow.note("/mnt/fast/Films/a.mkv", 100)
    ow.note("/mnt/fast/Films/a.mkv", 105)
    ow.note("/mnt/fast/Films/2019/b.mkv", 101)
    ow.note("/mnt/fast/Films0/c.mkv", 102)  # another folder whose name only starts the same
    ow.note("/mnt/fast/Photos/d.jpg", 103)
    assert ow.flush() == 4 and ow.flush() == 0
    ow.note("/mnt/fast/Films/a.mkv", 90)  # an older day never replaces a newer one
    assert ow.last_opened("/mnt/fast/Films/") == {"/mnt/fast/Films/a.mkv": 105, "/mnt/fast/Films/2019/b.mkv": 101}


def test_a_folder_or_single_files_can_be_forgotten():
    for name in ("a", "b", "c"):
        ow.note(f"/mnt/fast/Films/{name}", 100)
    ow.note("/mnt/fast/Photos/d.jpg", 100)
    ow.flush()
    ow.note("/mnt/fast/Films/b", 101)  # seen, not yet written: forgetting it covers that too
    ow.forget_files(["/mnt/fast/Films/a", "/mnt/fast/Films/b"])
    assert ow.last_opened("/mnt/fast/Films") == {"/mnt/fast/Films/c": 100}
    assert ow.forget("/mnt/fast/Films") == 1
    assert ow.last_opened("/mnt/fast/Films") == {} and ow.last_opened("/mnt/fast/Photos") == {
        "/mnt/fast/Photos/d.jpg": 100
    }


def test_today_is_a_whole_day_number():
    assert ow.today(86400 * 3 + 5) == 3 and ow.today(86400 * 4 - 1) == 3


def test_a_file_is_wanted_under_the_path_kiboto_or_the_host_knows_it_by():
    prefixes = (("/host/pool/Films/", "/mnt/fast/Films/"), ("/mnt/fast/Films/", "/mnt/fast/Films/"))
    assert ow.wanted("/mnt/fast/Films/a.mkv", prefixes) == "/mnt/fast/Films/a.mkv"
    assert ow.wanted("/host/pool/Films/2019/b.mkv", prefixes) == "/mnt/fast/Films/2019/b.mkv"
    assert ow.wanted("/mnt/fast/Films2/a.mkv", prefixes) is None
    assert ow.wanted("/mnt/fast/Photos/a.jpg", prefixes) is None


def _event(path, pid):
    fd = os.open(path, os.O_RDONLY)
    return ow.EVENT.pack(ow.EVENT.size, 3, 0, ow.EVENT.size, ow.FAN_OPEN, fd, pid), fd


def test_only_opens_from_outside_kiboto_in_a_watched_folder_count(record):
    folder = record / "Films"
    folder.mkdir()
    (record / "Other").mkdir()
    for p in (folder / "outside.mkv", folder / "kiboto.mkv", record / "Other" / "x.txt"):
        p.write_text("x")
    real = os.path.realpath(folder)
    data, fds = b"", []
    for path, pid in ((f"{real}/outside.mkv", 0), (f"{real}/kiboto.mkv", 4321), (f"{record}/Other/x.txt", 0)):
        raw, fd = _event(path, pid)
        data += raw
        fds.append(fd)
    data += ow.EVENT.pack(ow.EVENT.size, 3, 0, ow.EVENT.size, ow.FAN_OPEN, -1, 0)  # the kernel's "queue overflowed"
    assert ow.read_events(data + b"\x01\x02", ((real + "/", "/mnt/fast/Films/"),)) == ["/mnt/fast/Films/outside.mkv"]
    for fd in fds:  # each event's handle was closed, whether it counted or not
        with pytest.raises(OSError):
            os.fstat(fd)


def test_nothing_is_watched_until_a_folder_is_given():
    ow.watch([], [])
    assert ow.status() == {"watching": False, "folders": [], "error": ""}


def test_when_kiboto_was_last_listening_is_kept():
    assert ow.last_alive() is None
    ow.mark_alive(1000.0)
    ow.mark_alive(2000.5)
    assert ow.last_alive() == 2000.5
