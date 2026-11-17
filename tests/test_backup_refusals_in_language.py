"""Backup refusals carry their message key, so the Backup page says them in the reader's language."""

import pytest

from backend.errors import SaidError
from backend.services import backup_engine as be


def test_passphrase_refusals_say_how():
    with pytest.raises(SaidError) as e:
        be.decrypt_backup(b"plain zip", "x")
    assert e.value.text["msg_key"] == "srv.backup_not_encrypted"
    with pytest.raises(SaidError) as e:
        be.decrypt_backup(be.ENCRYPTED_MAGIC + b"0" * 40, "")
    assert e.value.text["msg_key"] == "srv.backup_needs_passphrase"
    with pytest.raises(SaidError) as e:
        be.decrypt_backup(be.ENCRYPTED_MAGIC + b"0" * 60, "wrong-pass")
    assert e.value.text["msg_key"] == "srv.backup_wrong_passphrase"


def test_sources_and_settings_jobs_say_how(monkeypatch):
    with pytest.raises(SaidError) as e:
        be.checked_subvolume("/etc")
    assert e.value.text["msg_key"] == "srv.backup_source_outside"
    for job, pw, key in (
        ({"destination_type": "local_folder", "local_path": "/etc"}, "short", "srv.backup_passphrase_short"),
        ({"destination_type": "local_folder", "local_path": "/etc"}, "long-enough-1", "srv.backup_dest_outside"),
        ({"destination_type": "remote", "remote_name": ""}, "long-enough-1", "srv.backup_choose_remote"),
        ({"destination_type": "ftp"}, "long-enough-1", "srv.backup_settings_where"),
    ):
        with pytest.raises(SaidError) as e:
            be._settings_job_checks(job, pw)
        assert e.value.text["msg_key"] == key
