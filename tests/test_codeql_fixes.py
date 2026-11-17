"""Code-scanning fixes of 17 Nov 2026: names from a request never lead out of their folder, logo
fetches stay on image files, and unexpected error text stays in the server log."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.services import vm_store


@pytest.mark.parametrize("bad", ["..", "../x", "a/b", "", "x" * 65, "a b"])
def test_a_vm_id_never_names_a_path(bad):
    with pytest.raises(ValueError):
        vm_store.checked_vm_id(bad)
    with pytest.raises(ValueError):
        vm_store.vm_file(bad, "qemu.pid")


def test_a_vm_file_stays_in_its_folder():
    assert vm_store.vm_file("vm-1", "qemu.pid").endswith("/vms/vm-1/qemu.pid")
    with pytest.raises(ValueError):
        vm_store.vm_file("vm-1", "../../escape")


def test_qemu_helpers_refuse_a_bad_id():
    from backend.services import vm_qemu

    assert vm_qemu._is_qemu_process_alive("..") is False
    with pytest.raises(ValueError):
        vm_qemu._sync_cleanup_qemu_process("../..")


def test_an_upload_name_stays_in_its_folder(tmp_path):
    from backend.api.files import uploads

    assert uploads._inside(str(tmp_path), "a.txt") == str(tmp_path / "a.txt")
    for bad in ("../a.txt", "sub/a.txt", "..", "/etc/passwd"):
        with pytest.raises(HTTPException):
            uploads._inside(str(tmp_path), bad)
    (tmp_path / "a.txt").write_text("x")
    assert uploads._free_name(str(tmp_path), "a.txt") == "a (2).txt"
    assert uploads._landing_name(str(tmp_path), "b.txt", "keep_both") == "b.txt"


def test_a_home_stays_in_the_homes_folder(tmp_path):
    from backend.services import user_spaces

    assert user_spaces._within(str(tmp_path), "anna") == str(tmp_path / "anna")
    for bad in ("..", "../x", "."):
        with pytest.raises(ValueError):
            user_spaces._within(str(tmp_path), bad)
    with patch("backend.users_db.get_user_by_username", return_value={}):
        with pytest.raises(ValueError):
            user_spaces.home_of("..")


def test_logos_are_image_files_on_the_two_hosts():
    from backend.services.catalog_logos import allowed

    assert allowed("https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/jellyfin.png")
    assert allowed("https://raw.githubusercontent.com/Lissy93/portainer-templates/main/images/x.JPG")
    assert not allowed("https://cdn.jsdelivr.net/gh/someone/repo/secrets.json")
    assert not allowed("https://cdn.jsdelivr.net/gh/a/b/x.png;evil")
    assert not allowed("https://cdn.jsdelivr.net/gh/a/b/%2e%2e/x.png")


def test_a_failed_command_says_what_failed_without_its_error_text():
    from backend.hardware.pal.base import StoragePlatformAdapter
    from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter

    adapter = GenericLinuxStorageAdapter(pool_path="/mnt/storage")
    with patch("subprocess.run", side_effect=RuntimeError("secret /internal/path detail")):
        code, out, err = adapter._run_cmd(["btrfs", "scrub", "start"])
        assert code == 1 and "secret" not in err and err.startswith("btrfs could not be run")
        code, out, err = StoragePlatformAdapter._run_cmd(adapter, ["zfs", "list"])
        assert code == 1 and "secret" not in err and err.startswith("zfs could not be run")


def test_a_folder_that_could_not_be_moved_is_said_without_paths():
    from backend.api import auth

    with patch("backend.services.user_spaces.retire_home", side_effect=OSError("/mnt/user/homes/anna: busy")):
        res = auth._retire_files({"username": "anna"}, "keep", "", "/mnt/user/homes/anna")
    assert res["files"] == "error" and "/mnt" not in res["error"]
