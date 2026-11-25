"""On a machine Kiboto runs, the first-time code's notice is written by the host door: Kiboto runs as
the user kiboto and cannot write /etc (found by the disaster drill on a fresh install, 25 Nov 2026)."""

from backend import door, first_run, runtime
from backend.services import host_door


def test_the_door_writes_and_clears_the_notice_with_no_argument():
    assert host_door.OPERATIONS["firstrun.notice"].args == {}
    assert host_door.OPERATIONS["firstrun.clear"].args == {}


def test_show_and_clear_go_through_the_door(monkeypatch):
    asked = []
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    monkeypatch.setattr(door, "via", lambda op, here, **a: asked.append((op, here)))
    assert first_run.show("ABCD-EFGH-JKLM") is True
    first_run.refresh()
    first_run.clear()
    assert asked == [
        ("firstrun.notice", first_run.refresh_here),
        ("firstrun.notice", first_run.refresh_here),
        ("firstrun.clear", first_run.clear_here),
    ]


def test_nothing_off_a_managed_host(monkeypatch):
    monkeypatch.setattr(runtime, "managed_host", lambda: False)
    monkeypatch.setattr(door, "via", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked the door")))
    assert first_run.show("x") is False
    first_run.refresh()
    first_run.clear()


def test_the_door_side_writes_the_code_from_the_file_and_removes_it_after(tmp_path, monkeypatch):
    from backend import config

    code_file = tmp_path / "initial-admin-password"
    code_file.write_text("ABCD-EFGH-JKLM\n")
    monkeypatch.setattr(config, "initial_password_file", lambda: str(code_file))
    monkeypatch.setattr(first_run, "ISSUE", str(tmp_path / "issue.d" / "kiboto.issue"))
    monkeypatch.setattr(first_run, "MOTD", str(tmp_path / "motd.d" / "kiboto"))
    first_run.refresh_here()
    assert "ABCD-EFGH-JKLM" in (tmp_path / "issue.d" / "kiboto.issue").read_text()
    assert "ABCD-EFGH-JKLM" in (tmp_path / "motd.d" / "kiboto").read_text()
    code_file.unlink()
    first_run.refresh_here()
    assert not (tmp_path / "issue.d" / "kiboto.issue").exists() and not (tmp_path / "motd.d" / "kiboto").exists()
