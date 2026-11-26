"""New ZFS pools keep to ZFS 2.3's features (Debian 13's own ZFS), so they open there and later."""

from backend.hardware.pal import generic_linux


def test_a_new_pool_is_limited_to_zfs_2_3_where_the_list_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(generic_linux, "ZFS_COMPAT_DIRS", (str(tmp_path / "none"), str(tmp_path)))
    assert generic_linux.zfs_compat_args() == []  # an older ZFS without the list: as before
    (tmp_path / "openzfs-2.3-linux").write_text("# features\n")
    assert generic_linux.zfs_compat_args() == ["-o", "compatibility=openzfs-2.3-linux"]


def test_the_install_takes_debian_13s_own_zfs_and_tests_it():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    tested = json.loads((root / "packaging" / "host-set.json").read_text())["tested_with"]
    assert tested["zfs-dkms"] == tested["zfsutils-linux"] and "bpo" not in tested["zfs-dkms"]
    assert tested["zfs-dkms"].startswith("2.3.")
