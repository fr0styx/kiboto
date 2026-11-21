"""A VM's disk, ISO or shared folder never reaches Kiboto's own data, whatever path names it."""

import pytest
from fastapi import HTTPException

from backend.services import vm_store


@pytest.fixture
def pool(tmp_path, monkeypatch):
    import backend.fsutil as fsutil
    from backend.services import path_access

    root = tmp_path / "mnt" / "user"
    ours = root / "appdata" / "kiboto" / "data"
    ours.mkdir(parents=True)
    (ours / "users.db").write_bytes(b"people")
    (root / "isos").mkdir()
    (root / "isos" / "debian.iso").write_bytes(b"iso")
    (root / "vmdisks").mkdir()
    (root / "vmdisks" / "extra.qcow2").write_bytes(b"disk")
    (root / "Films").mkdir()
    monkeypatch.setattr(path_access, "ALLOWED_BROWSE_ROOTS", [str(root)], raising=False)
    monkeypatch.setattr(fsutil, "protected_dirs", lambda: [str(root / "appdata" / "kiboto"), str(ours)])
    return root


def test_kibotos_files_are_not_a_vm_disk_or_iso(pool):
    db = str(pool / "appdata" / "kiboto" / "data" / "users.db")
    with pytest.raises(HTTPException):
        vm_store._validate_vm_inputs([{"path": db}], None, [])
    with pytest.raises(HTTPException):
        vm_store._validate_vm_inputs([], db, [])
    vm_store._validate_vm_inputs(
        [{"path": str(pool / "vmdisks" / "extra.qcow2")}], str(pool / "isos" / "debian.iso"), []
    )


@pytest.mark.parametrize("folder", ["appdata", "appdata/kiboto", ""])
def test_a_folder_holding_kibotos_data_is_not_shared_with_a_vm(pool, folder):
    with pytest.raises(HTTPException):
        vm_store._validate_vm_inputs([], None, [{"host_path": str(pool / folder), "mode": "ro"}])


def test_an_ordinary_folder_is_shared(pool):
    vm_store._validate_vm_inputs([], None, [{"host_path": str(pool / "Films"), "mode": "rw"}])
