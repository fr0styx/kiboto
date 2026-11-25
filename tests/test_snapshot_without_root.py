"""Without root (the web user), a snapshot leaves out the files that aren't Kiboto's (Samba's private
databases are root's) instead of failing: the restore from the pools stopped there (OS audit drill)."""

import json
import os

import pytest

from backend.services import data_snapshot


@pytest.fixture
def data(tmp_path):
    d = tmp_path / "data"
    (d / "samba" / "private").mkdir(parents=True)
    (d / "users.json").write_text("{}")
    (d / "door-audit.log").write_text("root's")
    (d / "samba" / "smb.conf").write_text("[global]")
    (d / "samba" / "private" / "passdb.tdb").write_text("root's")
    return d


def _not_kibotos(monkeypatch, *names):
    real = os.access
    monkeypatch.setattr(data_snapshot.os, "geteuid", lambda: 999)
    monkeypatch.setattr(data_snapshot.os, "access", lambda p, m: not str(p).endswith(names) and real(p, m))


def test_files_that_arent_kibotos_are_left_out_and_named(data, monkeypatch):
    _not_kibotos(monkeypatch, "passdb.tdb", "door-audit.log")
    dest = data_snapshot.take_snapshot(str(data), label="pre-restore")
    assert os.path.exists(os.path.join(dest, "users.json"))
    assert os.path.exists(os.path.join(dest, "samba", "smb.conf"))
    assert not os.path.exists(os.path.join(dest, "samba", "private", "passdb.tdb"))
    with open(os.path.join(dest, data_snapshot.MANIFEST)) as f:
        manifest = json.load(f)
    assert manifest["left_out"] == ["door-audit.log", os.path.join("samba", "private", "passdb.tdb")]


def test_as_root_nothing_is_left_out(data, monkeypatch):
    monkeypatch.setattr(data_snapshot.os, "geteuid", lambda: 0)
    dest = data_snapshot.take_snapshot(str(data), label="x")
    assert os.path.exists(os.path.join(dest, "samba", "private", "passdb.tdb"))
    with open(os.path.join(dest, data_snapshot.MANIFEST)) as f:
        assert json.load(f)["left_out"] == []
