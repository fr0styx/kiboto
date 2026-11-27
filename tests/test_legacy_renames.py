"""Names stored before the rebrand are renamed once where they are stored (backend/legacy_names.py);
the rest of the code knows only Kiboto's names."""

import json
import os

from backend import legacy_names
from backend.fsutil import atomic_write_json
from backend.services import app_after_start


def test_saved_app_definitions_take_kibotos_names(tmp_path):
    old = {
        "apps": [
            {
                "id": "wiki",
                "join_zettnas_network": True,
                "env": {"API": "http://{{zettnas}}:8082/api", "N": 3},
                "after_start": [{"url": "http://{{host}}:{{port}}/setup", "body": ["{{zettnas}}"]}],
            }
        ]
    }
    (tmp_path / "sideloaded_apps.json").write_text(json.dumps(old))
    (tmp_path / "catalog_cache").mkdir()
    (tmp_path / "catalog_cache" / "community.json").write_text(json.dumps(old))
    (tmp_path / "catalog_cache" / "fresh.json").write_text(
        json.dumps({"apps": [{"id": "x", "join_kiboto_network": True}]})
    )
    assert legacy_names.rename_app_files(str(tmp_path), atomic_write_json) == 2
    for name in ("sideloaded_apps.json", "catalog_cache/community.json"):
        text = (tmp_path / name).read_text()
        assert "zettnas" not in text
        app = json.loads(text)["apps"][0]
        assert app["join_kiboto_network"] is True and app["env"] == {"API": "http://{{kiboto}}:8082/api", "N": 3}
        assert app["after_start"][0]["body"] == ["{{kiboto}}"]
    assert legacy_names.rename_app_files(str(tmp_path), atomic_write_json) == 0  # once done, nothing to do
    assert legacy_names.rename_app_files(str(tmp_path / "missing"), atomic_write_json) == 0


def test_the_placeholders_are_kibotos_only():
    ctx = app_after_start.context("nas.local", 8082)
    assert set(ctx) == {"host", "port", "kiboto", "arch"}


def test_rename_at_start_reads_the_data_folder(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(legacy_names, "rename_app_files", lambda d, w: seen.append(d) or 0)
    legacy_names.rename_at_start(str(tmp_path), atomic_write_json)
    assert seen == [str(tmp_path)]


def test_a_broken_file_is_left(tmp_path):
    good = tmp_path / "sideloaded_apps.json"
    good.write_text('{"apps": [{"env": "{{zettnas}}"}]}')
    (tmp_path / "catalog_cache").mkdir()
    (tmp_path / "catalog_cache" / "broken.json").write_text("{not json")
    assert legacy_names.rename_app_files(str(tmp_path), atomic_write_json) == 1
    assert "{{kiboto}}" in good.read_text()
    assert (tmp_path / "catalog_cache" / "broken.json").read_text() == "{not json"


def test_kibotos_own_containers_from_before_are_recognised():
    assert legacy_names.made_before("/zettnas-toolkit") and legacy_names.made_before("zettnas-samba")
    assert not legacy_names.made_before("kiboto") and not legacy_names.made_before(None)


def test_existing_and_moved(tmp_path):
    (tmp_path / "old.txt").write_text("a")
    assert legacy_names.existing(str(tmp_path), "new.txt", "old.txt") == str(tmp_path / "old.txt")
    assert legacy_names.moved(str(tmp_path), "new.txt", "old.txt") == str(tmp_path / "new.txt")
    assert (tmp_path / "new.txt").read_text() == "a" and not (tmp_path / "old.txt").exists()
    assert legacy_names.existing(str(tmp_path), "new.txt", "old.txt") == str(tmp_path / "new.txt")
    (tmp_path / "old.txt").write_text("b")  # both there: the new one is used, the old left alone
    assert legacy_names.moved(str(tmp_path), "new.txt", "old.txt") == str(tmp_path / "new.txt")
    assert (tmp_path / "old.txt").read_text() == "b"


def test_a_refused_rename_keeps_using_the_old_one(tmp_path, monkeypatch):
    (tmp_path / "old").mkdir()

    def refused(a, b):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(legacy_names.os, "rename", refused)
    assert legacy_names.moved(str(tmp_path), "new", "old") == str(tmp_path / "old")


def test_the_data_folder_keeps_its_mark_under_the_new_name(tmp_path):
    from backend import fsutil

    (tmp_path / legacy_names.OLD_DATA_MARKER).write_text("abc123\n")
    assert fsutil.data_id(str(tmp_path)) == "abc123"
    assert (tmp_path / fsutil.DATA_MARKER).read_text().strip() == "abc123"
    assert not (tmp_path / legacy_names.OLD_DATA_MARKER).exists()


def test_an_encrypted_folders_files_under_the_old_name_stay_protected():
    from backend import fsutil

    for name in (fsutil.ENCRYPTED_HIDDEN, legacy_names.OLD_ENCRYPTED_HIDDEN):
        assert fsutil.encrypted_refused(f"/mnt/storage/docs/{name}/tax")
        flags = fsutil.protected_rclone_excludes("")
        assert f"**/{name}/**" in flags and f"**/{name}" in flags


def test_the_hidden_folder_is_renamed_only_while_nothing_of_its_share_is_open(tmp_path, monkeypatch):
    from backend.services import encrypted_folders as ef

    docs, music = tmp_path / "docs", tmp_path / "music"
    for share in (docs, music):
        (share / legacy_names.OLD_ENCRYPTED_HIDDEN / "box").mkdir(parents=True)
    folders = {"tax": {"share": "docs"}, "songs": {"share": "music"}, "gone": {"share": "nowhere"}}
    monkeypatch.setattr(ef.ei, "folders", lambda: folders)
    monkeypatch.setattr(ef, "_mounted", lambda: {ef.plain_path("songs")})

    def share_path(share):
        if share == "nowhere":
            raise ValueError("no such share")
        return str(tmp_path / share)

    monkeypatch.setattr(ef, "_share_path", share_path)
    assert ef.cipher_path(str(docs), "tax") == str(docs / legacy_names.OLD_ENCRYPTED_HIDDEN / "tax")
    assert ef.rename_hidden_folders() == 1
    assert (docs / ef.HIDDEN / "box").is_dir() and (music / legacy_names.OLD_ENCRYPTED_HIDDEN).is_dir()
    assert ef.cipher_path(str(docs), "tax") == str(docs / ef.HIDDEN / "tax")
    assert ef.rename_hidden_folders() == 0


def test_an_apps_passwords_move_to_the_new_name(tmp_path):
    from backend.services import app_catalog, immich_sso

    (tmp_path / legacy_names.OLD_APP_MADE_FILE).write_text(json.dumps({"db": "pw"}))
    assert app_catalog._stack_secrets(str(tmp_path)) == {"db": "pw"}
    assert (tmp_path / app_catalog.APP_MADE_FILE).exists() and not (tmp_path / legacy_names.OLD_APP_MADE_FILE).exists()
    assert immich_sso._secret_file(str(tmp_path)) == str(tmp_path / app_catalog.APP_MADE_FILE)


def test_a_settings_backup_made_before_still_opens():
    import os

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from backend.services import backup_engine as be

    new = be.encrypt_backup(b"zip bytes", "long passphrase 1")
    assert new.startswith(be.ENCRYPTED_MAGIC) and be.decrypt_backup(new, "long passphrase 1") == b"zip bytes"
    salt, nonce = os.urandom(16), os.urandom(12)
    magic = legacy_names.OLD_ENCRYPTED_MAGIC
    old = magic + salt + nonce + AESGCM(be._derive_key("long passphrase 1", salt)).encrypt(nonce, b"older", magic)
    assert be.decrypt_backup(old, "long passphrase 1") == b"older"


def test_settings_exports_from_before_count_toward_the_kept_number(tmp_path, monkeypatch):
    from backend import config
    from backend.services import backup_engine as be

    for n in ("20260101_000000", "20260102_000000"):
        (tmp_path / f"{legacy_names.OLD_EXPORT_PREFIX}{n}{legacy_names.OLD_SETTINGS_EXT}").write_bytes(b"x")
    (tmp_path / "unrelated.txt").write_text("keep")
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(tmp_path)])
    monkeypatch.setattr(be, "job_passphrase", lambda job: "long passphrase 1")
    monkeypatch.setattr(be, "generate_backup_zip_stream", lambda passphrase: __import__("io").BytesIO(b"blob"))
    out = be._export_settings({"destination_type": "local_folder", "local_path": str(tmp_path)}, 2)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert out.endswith(be.SETTINGS_EXT) and os.path.basename(out) in left
    assert left == sorted(
        [
            os.path.basename(out),
            f"{legacy_names.OLD_EXPORT_PREFIX}20260102_000000{legacy_names.OLD_SETTINGS_EXT}",
            "unrelated.txt",
        ]
    )


def test_a_dump_replaces_the_one_from_before():
    from backend.services import backup_hooks

    commands = [cmd for _pat, _kind, cmd in backup_hooks.DUMPS]
    assert all(
        "zettnas" not in c.replace(legacy_names.OLD_DUMP_NAMES[0], "").replace(legacy_names.OLD_DUMP_NAMES[1], "")
        for c in commands
    )
    assert f'rm -f "$D/{legacy_names.OLD_DUMP_NAMES[0]}"' in commands[0]
    assert f'rm -f "$D/{legacy_names.OLD_DUMP_NAMES[1]}"' in commands[3]


class _FakeSide:
    """The target side of a replication job: answers zfs list / ls, records what it is told."""

    remote = True

    def __init__(self, listing, refuse=False):
        self.listing, self.calls, self.refuse = listing, [], refuse

    def run(self, argv):
        self.calls.append(argv)
        if self.refuse and argv[1] in ("rename", "-T"):
            from backend.services.replication_engine import ReplicationError

            raise ReplicationError("cannot rename: permission denied")
        return self.listing if argv[:2] in (["zfs", "list"], ["ls", "-1"]) else ""


def test_a_zfs_jobs_snapshots_take_kibotos_name_on_both_sides(monkeypatch):
    from backend.services import replication_engine as re_

    old = legacy_names.OLD_REPL_PREFIX + "abcdef12-"
    local = []
    monkeypatch.setattr(
        re_,
        "_run",
        lambda argv: local.append(argv) or (f"tank/data@{old}1\ntank/data@other" if argv[1] == "list" else ""),
    )
    side = _FakeSide(f"bak/data@{old}1\nbak/data@{old}2")
    job = {
        "id": "abcdef1234",
        "source_pool": "tank",
        "source_dataset": "data",
        "target_pool": "bak",
        "target_dataset": "data",
        "last_snapshot": f"{old}2",
    }
    assert re_._Zfs(job, side).adopt_old_names() == 3
    renames = [c for c in side.calls if c[1] == "rename"] + [c for c in local if c[1] == "rename"]
    assert renames == [
        ["zfs", "rename", "--", f"bak/data@{old}1", "bak/data@kiboto-repl-abcdef12-1"],
        ["zfs", "rename", "--", f"bak/data@{old}2", "bak/data@kiboto-repl-abcdef12-2"],
        ["zfs", "rename", "--", f"tank/data@{old}1", "tank/data@kiboto-repl-abcdef12-1"],
    ]
    assert job["last_snapshot"] == "kiboto-repl-abcdef12-2"


def test_a_refused_rename_on_the_target_leaves_the_source_as_it_was(monkeypatch):
    import pytest

    from backend.services import replication_engine as re_

    old = legacy_names.OLD_REPL_PREFIX + "abcdef12-"
    local = []
    monkeypatch.setattr(re_, "_run", lambda argv: local.append(argv) or f"tank/data@{old}1")
    job = {"id": "abcdef1234", "source_pool": "tank", "target_pool": "bak", "last_snapshot": f"{old}1"}
    with pytest.raises(re_.ReplicationError, match="permission denied"):
        re_._Zfs(job, _FakeSide(f"bak@{old}1", refuse=True)).adopt_old_names()
    assert not [c for c in local if c[1] == "rename"] and job["last_snapshot"] == f"{old}1"


def test_a_btrfs_jobs_snapshots_take_kibotos_name(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from backend.services import replication_engine as re_

    old = legacy_names.OLD_REPL_PREFIX + "abcdef12-"
    pool = tmp_path / "pool"
    (pool / legacy_names.OLD_REPL_DIR / "abcdef12" / f"{old}1").mkdir(parents=True)
    side = _FakeSide(f"{old}1\nunrelated")
    adapter = SimpleNamespace(get_pool_path=lambda pid: str(pool))
    job = {
        "id": "abcdef1234",
        "source_pool": "p",
        "target_pool": "/backup",
        "target_dataset": "nas",
        "last_snapshot": f"{old}1",
    }
    engine = re_._Btrfs(job, side, adapter)
    assert engine.adopt_old_names() == 2
    assert side.calls[-1] == ["mv", "-T", "--", f"/backup/nas/{old}1", "/backup/nas/kiboto-repl-abcdef12-1"]
    assert (pool / ".kiboto-repl" / "abcdef12" / "kiboto-repl-abcdef12-1").is_dir()
    assert not (pool / legacy_names.OLD_REPL_DIR / "abcdef12").exists()
    assert job["last_snapshot"] == "kiboto-repl-abcdef12-1"


def test_the_offsite_host_keeps_its_mark_in_kibotos_name(tmp_path, monkeypatch):
    from backend.services import offsite_backup as ob

    monkeypatch.setattr(ob, "DATA_DIR", str(tmp_path))
    (tmp_path / "offsite_host").write_text(legacy_names.OLD_RESTIC_HOST_START + "0a1b2c3d\n")
    assert ob.host_id() == "kiboto-0a1b2c3d"
    assert (tmp_path / "offsite_host").read_text().strip() == "kiboto-0a1b2c3d"
    (tmp_path / "offsite_host").write_text("something else\n")
    assert ob.host_id().startswith("kiboto-") and ob.host_id() != "kiboto-0a1b2c3d"


def test_a_repos_old_snapshots_are_retagged_and_moved_once(tmp_path, monkeypatch):
    from backend.services import offsite_backup as ob

    monkeypatch.setattr(ob, "DATA_DIR", str(tmp_path))
    (tmp_path / "offsite_host").write_text(legacy_names.OLD_RESTIC_HOST_START + "0a1b2c3d\n")  # from before
    ran = []
    answers = {"fail": True}

    def restic(repo, args, timeout=0):
        ran.append(args)
        if answers["fail"]:
            raise ob.ResticError("repository is already locked")
        return ""

    monkeypatch.setattr(ob, "run_restic", restic)
    repo = {"id": "r1", "name": "Cloud"}
    assert ob.rename_old_marks(repo) is False  # tried again next time
    assert (tmp_path / "offsite_host").read_text().strip() == "kiboto-0a1b2c3d"
    answers["fail"] = False
    assert ob.rename_old_marks(repo) is True
    old_tag, old_host = legacy_names.OLD_BACKUP_TAG, legacy_names.OLD_RESTIC_HOST_START + "0a1b2c3d"
    assert ran[-2:] == [
        ["tag", "--tag", old_tag, "--add", "kiboto", "--remove", old_tag],
        ["rewrite", "--host", old_host, "--new-host", "kiboto-0a1b2c3d", "--forget"],
    ]
    ran.clear()
    assert ob.rename_old_marks(repo) is True and ran == []  # done once


def test_old_and_new_file_backups_are_listed_restored_and_pruned_alike():
    from backend.services import offsite_backup as ob

    assert ob.FILE_TAGS == ["--tag", "kiboto", "--tag", legacy_names.OLD_BACKUP_TAG]
    args = ob._forget_args({"daily": 7, "weekly": 4, "monthly": 6})
    assert args[args.index("forget") + 2 : args.index("forget") + 6] == ob.FILE_TAGS


def test_the_search_indexs_model_ids_take_kibotos_name():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    old = legacy_names.OLD_LEXICAL_MODEL
    conn.executescript(
        "CREATE TABLE indexed_files (file_id INTEGER PRIMARY KEY, parse_status TEXT, embedding_model TEXT);"
        "CREATE TABLE document_chunks (chunk_id INTEGER PRIMARY KEY, embedding_model TEXT);"
        f"CREATE INDEX idx_files_fallback_vectors ON indexed_files(file_id) WHERE embedding_model = '{old}';"
    )
    conn.execute("INSERT INTO indexed_files (parse_status, embedding_model) VALUES ('ok', ?), ('ok', 'eg2')", (old,))
    conn.execute("INSERT INTO document_chunks (embedding_model) VALUES (?), (?)", (old, legacy_names.OLD_UNIFIED_MODEL))
    assert legacy_names.rename_index_models(conn, "kiboto_lexical_384d", "kiboto-unified-384-v2") == 3
    assert [r[0] for r in conn.execute("SELECT embedding_model FROM indexed_files")] == ["kiboto_lexical_384d", "eg2"]
    assert [r[0] for r in conn.execute("SELECT embedding_model FROM document_chunks")] == [
        "kiboto_lexical_384d",
        "kiboto-unified-384-v2",
    ]
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'idx_files_fallback_vectors'").fetchone()
    assert legacy_names.rename_index_models(conn, "kiboto_lexical_384d", "kiboto-unified-384-v2") == 0
    assert legacy_names.rename_index_models(sqlite3.connect(":memory:"), "a", "b") == 0  # no tables yet


def test_the_search_settings_name_the_own_embedding_by_its_new_id(tmp_path, monkeypatch):
    from backend.services import rag_engine

    cfg = tmp_path / "rag_config.json"
    cfg.write_text(json.dumps({"embedding_model": legacy_names.OLD_LEXICAL_MODEL, "enabled": True}))
    monkeypatch.setattr(rag_engine, "RAG_CONFIG_PATH", str(cfg))
    rag_engine._rename_old_config_model()
    assert json.loads(cfg.read_text()) == {"embedding_model": "kiboto_lexical_384d", "enabled": True}


def test_an_install_without_old_backups_renames_nothing(tmp_path, monkeypatch):
    from backend.services import offsite_backup as ob

    monkeypatch.setattr(ob, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ob, "run_restic", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no restic")))
    assert ob.rename_old_marks({"id": "r1", "name": "Cloud"}) is True


def _old_seal(plain, secret):
    """A value sealed the way of before the rebrand ("enc1:")."""
    import base64
    import hashlib

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = hashlib.sha256(legacy_names.OLD_BOX_KEY_START + secret.encode()).digest()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plain.encode(), legacy_names.OLD_BOX_AAD)
    return "enc1:" + base64.urlsafe_b64encode(nonce + ct).decode()


def test_a_value_sealed_before_opens_and_new_ones_use_the_new_box(monkeypatch):
    from backend import config, secret_box

    monkeypatch.setattr(config, "SECRET_KEY", "k" * 40)
    old = _old_seal("JBSWY3DPEHPK3PXP", "k" * 40)
    assert secret_box.is_sealed(old) and secret_box.is_old(old)
    assert secret_box.unseal(old) == "JBSWY3DPEHPK3PXP"
    assert secret_box.unseal_with(old, "k" * 40) == "JBSWY3DPEHPK3PXP"
    new = secret_box.seal("JBSWY3DPEHPK3PXP")
    assert new.startswith("enc2:") and not secret_box.is_old(new) and secret_box.unseal(new) == "JBSWY3DPEHPK3PXP"


def test_every_settings_file_and_the_users_database_are_sealed_again_once(tmp_path, monkeypatch):
    from backend import config, secret_box
    from backend.services import key_rotation

    monkeypatch.setattr(config, "SECRET_KEY", "k" * 40)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    old = _old_seal("pw", "k" * 40)
    (tmp_path / "snmp.json").write_text(json.dumps({"auth": old, "nested": [{"secret": old}], "n": 1}))
    (tmp_path / "plain.json").write_text(json.dumps({"x": "nothing sealed"}))
    (tmp_path / "theirs.json").write_text(json.dumps({"v": _old_seal("pw", "other-install-key-xxxxxxxxxxxx")}))
    # the users database and the services' own stores are left out here: the settings files only
    monkeypatch.setattr(
        key_rotation, "reseal_everything", lambda: {"mfa": 0, "other": key_rotation._reseal_json_files()}
    )
    assert key_rotation.reseal_old_values() is True
    data = json.loads((tmp_path / "snmp.json").read_text())
    assert data["auth"].startswith("enc2:") and data["nested"][0]["secret"].startswith("enc2:") and data["n"] == 1
    assert secret_box.unseal(data["auth"]) == "pw"
    assert json.loads((tmp_path / "theirs.json").read_text())["v"].startswith("enc1:")  # not ours to open: left
    assert key_rotation.reseal_old_values() is False  # once


def test_a_recovery_code_made_before_is_still_accepted():
    from backend import totp
    from backend.passwords import hash_password

    code = "abcd-efgh"
    old_hash = hash_password(f"{legacy_names.OLD_RECOVERY_START}abcdefgh")
    ok, left = totp.verify_and_consume_recovery_code([old_hash, totp.hash_recovery_code("zzzz-zzzz")], code)
    assert ok and len(left) == 1
    assert totp.verify_and_consume_recovery_code([totp.hash_recovery_code(code)], code)[0]
    assert totp.verify_and_consume_recovery_code([totp._legacy_recovery_hash(code)], code)[0]


def test_an_ai_database_keyed_with_the_salt_of_before_is_encrypted_again(tmp_path, monkeypatch):
    import pytest

    from backend import db_crypto

    if not db_crypto.HAVE_SQLCIPHER:
        pytest.skip("no SQLCipher here")
    monkeypatch.setenv("KIBOTO_DATA_KEY", "a-data-key-of-enough-length")
    db_crypto._raw_key.cache_clear()
    path = str(tmp_path / "rag_index.db")
    conn = db_crypto.sqlite3.connect(path)
    conn.execute(f"PRAGMA key = {db_crypto._key_sql(legacy_names.OLD_KDF_SALT)}")
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES ('kept')")
    conn.commit()
    conn.close()
    assert not db_crypto._opens_with(path, db_crypto._KDF_SALT)
    copy = str(tmp_path / "copy.db")
    import shutil

    shutil.copy(path, copy)  # a backup's copy made before
    assert db_crypto.connect_encrypted(copy).execute("SELECT v FROM t").fetchone()[0] == "kept"
    assert db_crypto.prepare(path) == "converted"
    assert db_crypto._opens_with(path, db_crypto._KDF_SALT)
    assert db_crypto.connect(path).execute("SELECT v FROM t").fetchone()[0] == "kept"
    assert db_crypto.prepare(path) == "encrypted"
