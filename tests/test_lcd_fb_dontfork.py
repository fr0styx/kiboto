"""The LCD framebuffer mapping is kept out of child processes (graphics-memory warnings on fork)."""

import mmap
import os
import subprocess
import sys

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


# The fork runs in a fresh, single-threaded Python: forking the test runner itself (which has
# threads) makes Python warn that the child may deadlock.
_CHILD_CHECK = """
import mmap, os, sys
from backend.services.lcd_renderer import map_framebuffer
kept, plain = sys.argv[1], sys.argv[2]
with open(kept, "r+b") as a, open(plain, "r+b") as b:
    ma = map_framebuffer(a.fileno(), 4096)
    mb = mmap.mmap(b.fileno(), 4096, mmap.MAP_SHARED, mmap.PROT_WRITE)
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        with open("/proc/self/maps") as m:
            maps = m.read()
        os.write(w, (("K" if kept in maps else "-") + ("P" if plain in maps else "-")).encode())
        os._exit(0)
    os.close(w)
    print(os.read(r, 2).decode())
    os.waitpid(pid, 0)
"""


@pytest.mark.skipif(not hasattr(os, "fork") or not hasattr(mmap, "MADV_DONTFORK"), reason="Linux only")
def test_child_does_not_get_the_mapping(tmp_path):
    kept, plain = tmp_path / "fb0", tmp_path / "plain"
    kept.write_bytes(bytes(4096))
    plain.write_bytes(bytes(4096))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run(
        [sys.executable, "-c", _CHILD_CHECK, str(kept), str(plain)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=root,
        env={**os.environ, "PYTHONPATH": root},
    )
    assert out.returncode == 0, out.stderr
    # the plain mapping reaches the child (the check can see mappings); the framebuffer's does not
    assert out.stdout.strip() == "-P"
