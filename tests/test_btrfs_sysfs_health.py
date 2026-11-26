"""Kiboto OS's web process cannot run `btrfs filesystem show`: a btrfs mirror with a drive missing
is seen from what the kernel says under /sys/fs/btrfs, which anyone may read."""

from backend.hardware.pal import generic_linux as gl

UUID = "0d68d8be-7771-40fb-bdc4-ea56c44ae2f6"


def _sys(tmp_path, missing):
    base = tmp_path / "fs" / "btrfs" / UUID
    for devid, gone in missing.items():
        (base / "devinfo" / devid).mkdir(parents=True)
        (base / "devinfo" / devid / "missing").write_text("1\n" if gone else "0\n")
    (base / "devices").mkdir(parents=True)
    (base / "devices" / "vdd").write_text("")
    return str(tmp_path)


def test_a_missing_drive_is_seen_without_root(tmp_path):
    assert gl.btrfs_sysfs(UUID, _sys(tmp_path, {"1": False, "2": True})) == (["vdd"], True)


def test_a_whole_pool_says_so(tmp_path):
    assert gl.btrfs_sysfs(UUID, _sys(tmp_path, {"1": False, "2": False})) == (["vdd"], False)


def test_no_word_from_the_kernel_is_no_answer(tmp_path):
    assert gl.btrfs_sysfs(UUID, str(tmp_path)) is None  # not mounted here
    assert gl.btrfs_sysfs("../etc", str(tmp_path)) is None  # not a pool's id
    base = tmp_path / "fs" / "btrfs" / UUID / "devinfo" / "1"
    base.mkdir(parents=True)  # a kernel that does not say which drive is missing
    assert gl.btrfs_sysfs(UUID, str(tmp_path)) is None
