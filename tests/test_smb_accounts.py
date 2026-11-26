"""One system account per person on Kiboto's own file server: fixed numbers, folders handed to them."""

import os
import stat
import subprocess

import pytest

from backend import owned
from backend.services import samba_engine, smb_accounts


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(smb_accounts, "_file", lambda: str(tmp_path / "smb_accounts.json"))
    return tmp_path


def test_numbers_are_given_once_and_never_again(accounts, monkeypatch):
    assert smb_accounts.uid_of("Ann") == 20000 and smb_accounts.uid_of("ann") == 20000
    assert smb_accounts.uid_of("bob") == 20001
    assert smb_accounts.numbers({"bob", "Cy"}) == {
        "bob": 20001,
        "cy": 20002,
    }  # ann left, cy came  # ann's number is not given to cy
    assert smb_accounts.uid_of("ann") == 20000
    with pytest.raises(ValueError):
        smb_accounts.uid_of(" ")


def test_a_private_folder_goes_to_its_person(tmp_path, monkeypatch):
    home = tmp_path / "kim"
    home.mkdir()
    chowned = []
    monkeypatch.setattr(owned, "_me", lambda: 0)
    monkeypatch.setattr(owned, "_give", lambda p, u, g, expect=None: chowned.append((p, u, g)))
    monkeypatch.setattr(owned, "_ids", lambda user, group: (65534, 100))
    real = os.stat

    def owner(uid):
        def fake(path, *a, **k):
            st = real(path, *a, **k)
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, uid, 100, *st[6:10]))

        return fake

    for was in (0, 65534):  # root's, or written as the file server's user before
        chowned.clear()
        monkeypatch.setattr(owned.os, "stat", owner(was))
        assert owned.to_person(str(home), 20003) is True and chowned == [(str(home), 20003, 100)]
        assert stat.S_IMODE(real(home).st_mode) == 0o700
    chowned.clear()
    monkeypatch.setattr(owned.os, "stat", owner(1001))  # someone gave it another owner
    assert owned.to_person(str(home), 20003) is False and chowned == []


def test_the_scripts_are_given_every_persons_number(accounts, monkeypatch):
    monkeypatch.setattr(samba_engine, "_people_names", lambda: {"ann", "bob"})
    monkeypatch.setattr(samba_engine, "_serves_files", lambda: True)
    assert samba_engine._accounts_env() == ["KB_UIDS=ann:20000 bob:20001"]
    monkeypatch.setattr(samba_engine, "_serves_files", lambda: False)  # Unraid
    assert samba_engine._accounts_env() == []


def test_the_account_script_gives_each_person_their_number(tmp_path):
    """The script as the container runs it, with id/adduser/deluser played by a small shell file."""
    fake = tmp_path / "bin"
    fake.mkdir()
    db = tmp_path / "passwd"
    db.write_text("ann:1000\n")
    (fake / "id").write_text(f'#!/bin/sh\ngrep "^$2:" {db} | cut -d: -f2 | grep . || exit 1\n')
    (fake / "deluser").write_text(f'#!/bin/sh\nsed -i "/^$1:/d" {db}\n')
    (fake / "adduser").write_text(
        f'#!/bin/sh\nwhile [ $# -gt 1 ]; do [ "$1" = -u ] && u=$2; shift; done\necho "$1:$u" >> {db}\n'
    )
    for f in fake.iterdir():
        f.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "KB_UIDS": "ann:20000 bob:20001"}
    subprocess.run(["sh", "-c", samba_engine.ACCOUNTS_SCRIPT], env=env, check=True)
    assert sorted(db.read_text().split()) == ["ann:20000", "bob:20001"]  # ann made again with her number
    subprocess.run(["sh", "-c", samba_engine.ACCOUNTS_SCRIPT], env=env, check=True)
    assert sorted(db.read_text().split()) == ["ann:20000", "bob:20001"]  # nothing changes the second time
