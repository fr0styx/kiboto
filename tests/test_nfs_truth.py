"""NFS tells the truth about an install that has no NFS server.

Kiboto's container has no exportfs. There a folder could be "shared over NFS": the export was saved,
its file written where nothing reads it, apply_exports answered True and the status said "running"."""

import os
import pathlib
import subprocess

import pytest

from backend.errors import SaidError
from backend.hardware.pal_storage import GenericLinuxStorageAdapter
from backend.services import nfs_engine
from backend.services.nfs_engine import NfsEngine, NfsExportRule


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(nfs_engine, "NFS_DIR", str(tmp_path / "nfs"))
    monkeypatch.setattr(nfs_engine, "NFS_EXPORTS_FILE", str(tmp_path / "nfs" / "exports.json"))
    return NfsEngine(exports_d_path=str(tmp_path / "exports.d" / "kiboto.exports"))


def _rule(tmp_path):
    return NfsExportRule(name="films", path=str(tmp_path / "films"), clients="192.168.1.0/24")


def test_can_serve_follows_the_tool(monkeypatch):
    monkeypatch.undo()  # the fixture that pretends a server is there
    monkeypatch.setattr(nfs_engine.shutil, "which", lambda name: None)
    assert nfs_engine.can_serve() is False
    monkeypatch.setattr(nfs_engine.shutil, "which", lambda name: "/usr/sbin/" + name)
    assert nfs_engine.can_serve() is True


def test_a_file_nobody_reads_is_not_an_applied_export(engine, tmp_path, monkeypatch):
    def no_tool(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(nfs_engine.subprocess, "run", no_tool)
    engine._exports["films"] = _rule(tmp_path)
    assert engine.apply_exports() is False
    # the file is still written, for the day a server reads it
    assert "films" in pathlib.Path(engine._exports_d_file).read_text(encoding="utf-8")
    monkeypatch.setattr(nfs_engine.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "no"))
    assert engine.apply_exports() is False
    monkeypatch.setattr(nfs_engine.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    assert engine.apply_exports() is True


def test_the_file_from_before_the_rebrand_is_removed(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(nfs_engine.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    old = tmp_path / "exports.d" / nfs_engine.OLD_EXPORTS_NAME
    old.parent.mkdir()
    old.write_text("/mnt/old 10.0.0.0/8(rw)\n")
    engine._exports["films"] = _rule(tmp_path)
    engine.apply_exports()
    assert not old.exists() and os.path.isfile(engine._exports_d_file)


def test_status_is_the_server_not_the_settings(engine, tmp_path, monkeypatch):
    engine._exports["films"] = _rule(tmp_path)

    class Closed:
        def settimeout(self, _t):
            pass

        def connect_ex(self, _addr):
            return 111

        def close(self):
            pass

    import socket

    monkeypatch.setattr(socket, "socket", lambda *a, **k: Closed())
    monkeypatch.setattr(nfs_engine, "can_serve", lambda: False)
    st = engine.get_status()
    assert st.exports_count == 1 and st.running is False and st.served is False


def test_a_share_is_not_made_over_nfs_where_nothing_serves_it(tmp_path, monkeypatch):
    adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path))
    ran = []
    adapter._run_cmd = lambda cmd: (ran.append(cmd), (0, "", ""))[1]
    monkeypatch.setattr(nfs_engine, "can_serve", lambda: False)
    assert adapter.get_capabilities().nfs_served is False
    with pytest.raises(SaidError) as e:
        adapter.create_share(name="films", path=str(tmp_path / "films"), export_smb=False, export_nfs=True)
    assert e.value.text["msg_key"] == "srv.nfs_no_server"
    assert ran == [] and not (tmp_path / "films").exists()  # refused before anything was made
    monkeypatch.setattr(nfs_engine, "can_serve", lambda: True)
    assert adapter.get_capabilities().nfs_served is True
