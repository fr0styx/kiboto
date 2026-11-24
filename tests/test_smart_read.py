"""Reading a drive's health: here as root, through the host door as the unprivileged user."""

import subprocess

import pytest

from backend import door
from backend.hardware import smart_read
from backend.proc import TIMED_OUT


def test_as_root_smartctl_runs_here(monkeypatch):
    seen = []
    monkeypatch.setattr(smart_read.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        smart_read,
        "run_bounded",
        lambda cmd, timeout, **kw: seen.append((cmd, timeout)) or subprocess.CompletedProcess(cmd, 0, "ok", ""),
    )
    r = smart_read.run(["-j", "-H", "-A", "-d", "sat", "/dev/sda"], timeout=8)
    assert r.stdout == "ok" and seen == [(["smartctl", "-j", "-H", "-A", "-d", "sat", "/dev/sda"], 8)]


def test_as_the_web_user_the_door_reads_it(monkeypatch):
    calls = []
    monkeypatch.setattr(smart_read.os, "geteuid", lambda: 999)
    monkeypatch.setattr(door, "available", lambda sock=door.SOCK: True)
    monkeypatch.setattr(door, "call", lambda op, **a: calls.append((op, a)) or {"code": 4, "out": "{}", "err": "x"})
    r = smart_read.run(["-n", "standby", "-i", "/dev/sdb"], timeout=6)
    assert (r.returncode, r.stdout, r.stderr) == (4, "{}", "x")
    assert calls == [("disks.smartctl", {"args": ["-n", "standby", "-i", "/dev/sdb"], "limit": 6.0})]

    def refused(op, **a):
        raise door.DoorError("refused", "value")

    monkeypatch.setattr(door, "call", refused)
    assert smart_read.run(["-i", "/dev/sdb"], timeout=6).returncode == 127

    def gone(op, **a):
        raise FileNotFoundError("no door")

    monkeypatch.setattr(door, "call", gone)
    monkeypatch.setattr(
        smart_read, "run_bounded", lambda cmd, timeout, **kw: subprocess.CompletedProcess(cmd, 2, "standby", "")
    )
    assert smart_read.run(["-i", "/dev/sdb"], timeout=6).stdout == "standby"  # done here


def test_the_door_takes_only_read_only_flags_and_a_drive(monkeypatch):
    monkeypatch.setattr(smart_read.os.path, "realpath", lambda p: p)
    monkeypatch.setattr(smart_read.os, "stat", lambda p: smart_read.os.stat_result((0o060660,) + (0,) * 9))
    for good in (
        ["-j", "-H", "-A", "-d", "sat,auto", "-n", "standby", "/dev/sda"],
        ["-x", "-j", "-d", "nvme,0xffffffff", "/dev/nvme0n1"],
        ["-n", "standby", "-i", "/dev/vdb"],
    ):
        assert smart_read.checked(good) == good
    for bad in (
        [],
        ["-t", "long", "/dev/sda"],
        ["-s", "off", "/dev/sda"],
        ["-d", "sat; rm", "/dev/sda"],
        ["--set=standby,now", "/dev/sda"],
        ["-i", "/etc/passwd"],
        ["-i", 7],
    ):
        with pytest.raises(ValueError):
            smart_read.checked(bad)
    monkeypatch.setattr(smart_read.os, "stat", lambda p: smart_read.os.stat_result((0o100644,) + (0,) * 9))
    with pytest.raises(ValueError, match="drive"):
        smart_read.checked(["-i", "/dev/sda"])


def test_the_doors_answer(monkeypatch):
    monkeypatch.setattr(smart_read, "checked", lambda args: args)
    monkeypatch.setattr(
        smart_read, "run_bounded", lambda cmd, timeout, **kw: subprocess.CompletedProcess(cmd, TIMED_OUT, "", "")
    )
    got = smart_read.read_in_door(["-i", "/dev/sda"], 500)
    assert got == {"code": TIMED_OUT, "out": "", "err": "", "timed_out": True}
