"""A file that changed is seen as changed, also when its change time did not move.

On Debian 13's kernel (6.12) a file's change time moves only every few milliseconds: 2,000 quick
writes showed 18 different times, where a newer kernel shows 2,000. Caches that went by the time
alone then served the content from before the last save. Each test here saves twice and pins both
saves to the same time, which is what such a kernel does by itself."""

import json
import os

import pytest

from backend import api_tokens, fsutil
from backend.services import drive_notes, ip_block

T = 1_800_000_000_000_000_000  # one instant, in nanoseconds


def _same_instant(path):
    os.utime(path, ns=(T, T))


def test_a_stamp_tells_two_saves_at_one_instant_apart(tmp_path):
    path = str(tmp_path / "s.json")
    fsutil.atomic_write_json(path, {"n": 1})
    _same_instant(path)
    first = fsutil.file_stamp(path)
    fsutil.atomic_write_json(path, {"n": 2})  # same size, and then the same time
    _same_instant(path)
    second = fsutil.file_stamp(path)
    assert first[:2] == second[:2] and first != second  # only the file number differs
    with pytest.raises(OSError):
        fsutil.file_stamp(str(tmp_path / "missing.json"))


def test_the_json_cache_sees_a_change_made_outside_at_the_same_instant(tmp_path):
    path = str(tmp_path / "s.json")
    fsutil.atomic_write_json(path, {"n": 1})
    _same_instant(path)
    fsutil._JSON_CACHE.pop(path, None)
    assert fsutil.read_json_cached(path, max_age=0) == {"n": 1}
    other = tmp_path / "other.json"  # another process replaces the file, as the SFTP sidecar does
    other.write_text(json.dumps({"n": 2}))
    os.replace(other, path)
    _same_instant(path)
    assert fsutil.read_json_cached(path, max_age=0) == {"n": 2}


def test_the_cache_after_a_save_holds_the_files_real_stamp(tmp_path):
    path = str(tmp_path / "s.json")
    fsutil.atomic_write_json(path, {"n": 1})
    assert fsutil._JSON_CACHE[path][0] == fsutil.file_stamp(path)
    assert fsutil.read_json_cached(path, max_age=0) == {"n": 1}


def test_drive_notes_removed_at_the_same_instant_are_gone(tmp_path, monkeypatch):
    path = tmp_path / "drive_notes.json"
    monkeypatch.setattr(drive_notes, "NOTES_FILE", str(path))
    monkeypatch.setattr(drive_notes, "_cache", {"key": None, "data": {}})
    real = fsutil.atomic_write_json

    def save_at_one_instant(p, data, **kw):
        real(p, data, **kw)
        _same_instant(p)

    monkeypatch.setattr(drive_notes, "atomic_write_json", save_at_one_instant)
    drive_notes.save("WD-ABC123", "2024-05-01", "2027-05-01", "bay 3")
    assert "WD-ABC123" in drive_notes.all_notes()
    drive_notes.save("WD-ABC123")  # all empty removes them
    assert drive_notes.all_notes() == {}


def test_the_block_list_is_read_again_after_a_change_at_the_same_instant(tmp_path, monkeypatch):
    store = tmp_path / "ip_blocks.json"
    monkeypatch.setattr(ip_block, "STORE", str(store))
    monkeypatch.setattr(ip_block, "_cache", {"loaded": False, "checked": 0.0, "mtime": None, "blocks": {}})
    monkeypatch.setattr(ip_block, "RECHECK_S", 0.0)
    store.write_text(json.dumps({"203.0.113.9": {"until": None}, "203.0.113.8": {"until": None}}))
    _same_instant(store)
    assert ip_block.is_blocked("203.0.113.9")
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"203.0.113.7": {"until": None}, "203.0.113.8": {"until": None}}))  # the same size
    os.replace(other, store)
    _same_instant(store)
    assert not ip_block.is_blocked("203.0.113.9") and ip_block.is_blocked("203.0.113.7")


def test_tokens_saved_twice_at_one_instant_are_the_later_ones(tmp_path, monkeypatch):
    path = tmp_path / "api_tokens.json"
    monkeypatch.setattr(api_tokens, "TOKENS_FILE", str(path))
    monkeypatch.setattr(api_tokens, "_TOKENS_CACHE", {})
    monkeypatch.setattr(api_tokens, "_tokens_file_mtime_ns", None)
    path.write_text(json.dumps({"a": {"name": "one", "hash": "x" * 64, "scopes": []}}))
    _same_instant(path)
    assert list(api_tokens.load_tokens()) == ["a"]
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"b": {"name": "two", "hash": "y" * 64, "scopes": []}}))
    os.replace(other, path)
    _same_instant(path)
    assert list(api_tokens.load_tokens()) == ["b"]
