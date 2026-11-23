"""A folder a Mac makes on a shared folder stays writable: the Mac does not set its permissions
through NFS ACEs (they made it the share user\x27s alone, and the Mac then refused to write into it)."""

from backend.services.samba_engine import SambaEngine


def test_macs_do_not_set_folder_permissions_through_nfs_aces():
    conf = SambaEngine._DEFAULT_GLOBAL_CONFIG
    assert "fruit:nfs_aces = no" in conf
    assert conf.index("vfs objects = catia fruit") < conf.index("fruit:nfs_aces = no")
