"""A share exported over NFS only: its clients write as the file server's user, so on Kiboto's own
file server the folder goes to that user, as for SMB; it kept root's 755 and took no writes."""

from backend.services import nfs_engine


def _engine(tmp_path, monkeypatch, **rule):
    monkeypatch.setattr(nfs_engine, "NFS_EXPORTS_FILE", str(tmp_path / "exports.json"))
    e = nfs_engine.NfsEngine.__new__(nfs_engine.NfsEngine)
    e._exports = {"films": nfs_engine.NfsExportRule(name="films", path=str(tmp_path / "films"), **rule)}
    return e


def test_a_writable_squashed_export_goes_to_the_file_servers_user(tmp_path, monkeypatch):
    from backend import owned
    from backend.services import samba_engine

    handed = []
    monkeypatch.setattr(samba_engine, "_serves_files", lambda: True)
    monkeypatch.setattr(
        owned, "to_people", lambda path, user="nobody", group="users", mode=0o775: handed.append((path, user, group))
    )
    _engine(tmp_path, monkeypatch)._folders_to_file_server()
    assert handed == [(str(tmp_path / "films"), "nobody", "users")]


def test_read_only_root_squash_or_not_kibotos_file_server_is_left_alone(tmp_path, monkeypatch):
    from backend import owned
    from backend.services import samba_engine

    handed = []
    monkeypatch.setattr(owned, "to_people", lambda *a, **k: handed.append(a))
    monkeypatch.setattr(samba_engine, "_serves_files", lambda: True)
    _engine(tmp_path, monkeypatch, permission="ro")._folders_to_file_server()
    _engine(tmp_path, monkeypatch, squash="root_squash")._folders_to_file_server()
    monkeypatch.setattr(samba_engine, "_serves_files", lambda: False)
    _engine(tmp_path, monkeypatch)._folders_to_file_server()
    assert handed == []
