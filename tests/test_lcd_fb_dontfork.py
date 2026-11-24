"""The LCD framebuffer mapping is kept out of child processes (graphics-memory warnings on fork)."""

import mmap
import os

import pytest

from backend.services import lcd_renderer


def test_mapping_is_writable(tmp_path):
    f = tmp_path / "fb0"
    f.write_bytes(bytes(8192))
    with open(f, "r+b") as fh:
        mem = lcd_renderer.map_framebuffer(fh.fileno(), 8192)
        mem[:4] = b"\x01\x02\x03\x04"
        mem.flush()
        mem.close()
    assert f.read_bytes()[:4] == b"\x01\x02\x03\x04"


def test_mapping_is_marked_dont_fork(monkeypatch):
    calls = []

    class FakeMap:
        def __init__(self, fileno, size, flags, prot):
            calls.append(("map", size, flags, prot))

        def madvise(self, option):
            calls.append(("madvise", option))

    monkeypatch.setattr(lcd_renderer.mmap, "mmap", FakeMap)
    monkeypatch.setattr(lcd_renderer.mmap, "MADV_DONTFORK", 10, raising=False)
    lcd_renderer.map_framebuffer(3, 4096)
    assert calls == [("map", 4096, mmap.MAP_SHARED, mmap.PROT_WRITE), ("madvise", 10)]


def test_refused_advice_still_maps(monkeypatch):
    class FakeMap:
        def __init__(self, *a):
            pass

        def madvise(self, option):
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr(lcd_renderer.mmap, "mmap", FakeMap)
    monkeypatch.setattr(lcd_renderer.mmap, "MADV_DONTFORK", 10, raising=False)
    assert isinstance(lcd_renderer.map_framebuffer(3, 4096), FakeMap)


def test_no_advice_on_systems_without_it(monkeypatch):
    class FakeMap:
        def __init__(self, *a):
            pass

        def madvise(self, option):  # pragma: no cover - must not be called
            raise AssertionError("madvise called")

    monkeypatch.setattr(lcd_renderer.mmap, "mmap", FakeMap)
    monkeypatch.delattr(lcd_renderer.mmap, "MADV_DONTFORK", raising=False)
    assert isinstance(lcd_renderer.map_framebuffer(3, 4096), FakeMap)


@pytest.mark.skipif(not hasattr(os, "fork") or not hasattr(mmap, "MADV_DONTFORK"), reason="Linux only")
def test_child_does_not_get_the_mapping(tmp_path):
    f = tmp_path / "fb0"
    f.write_bytes(bytes(4096))
    with open(f, "r+b") as fh:
        mem = lcd_renderer.map_framebuffer(fh.fileno(), 4096)
        path = str(f)
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:  # child: is the framebuffer file still mapped here?
            os.close(r)
            try:
                with open("/proc/self/maps") as m:
                    seen = any(path in line for line in m)
            except Exception:
                seen = True
            os.write(w, b"1" if seen else b"0")
            os._exit(0)
        os.close(w)
        got = os.read(r, 1)
        os.close(r)
        os.waitpid(pid, 0)
        mem.close()
    assert got == b"0"
