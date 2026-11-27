"""SNMP reports each storage pool: on Kiboto OS the storage folder lies on the system disk, which
was reported as the pool."""

from backend.services import snmp_agent


def _mounts(tmp_path, lines):
    f = tmp_path / "mounts"
    f.write_text("".join(f"{dev} {point} {fs} rw 0 0\n" for dev, point, fs in lines))
    return str(f)


def test_each_pool_under_the_storage_folder_is_a_row(tmp_path):
    m = _mounts(
        tmp_path,
        [
            ("/dev/vda1", "/", "ext4"),
            ("tank", "/mnt/storage/tank", "zfs"),
            ("tank/homes", "/mnt/storage/tank/homes", "zfs"),  # a dataset of tank: not a pool of its own
            ("/dev/vdd", "/mnt/storage/media", "btrfs"),
            ("kiboto-tier", "/mnt/storage/docs/tiertest", "fuse.mergerfs"),
            ("/dev/sdb1", "/mnt/disks/usb", "vfat"),
        ],
    )
    assert snmp_agent.pool_mounts("/mnt/storage", m) == ["/mnt/storage/media", "/mnt/storage/tank"]


def test_a_storage_folder_that_is_the_mount_itself_is_the_one_row(tmp_path):
    m = _mounts(tmp_path, [("overlay", "/", "overlay"), ("/dev/md1", "/mnt/storage", "xfs")])
    assert snmp_agent.pool_mounts("/mnt/storage/", m) == ["/mnt/storage"]
    assert snmp_agent.pool_mounts("/mnt/storage", str(tmp_path / "missing")) == ["/mnt/storage"]


def test_the_mib_lists_the_pools(tmp_path, monkeypatch):
    import collections

    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "self" / "mounts").write_text(
        "tank /mnt/storage/tank zfs rw 0 0\n/dev/vdd /mnt/storage/media btrfs rw 0 0\n"
    )
    (proc / "meminfo").write_text("MemTotal: 1000 kB\nMemAvailable: 400 kB\n")
    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(snmp_agent.shutil, "disk_usage", lambda p: usage(4096 * 100, 4096 * 25, 4096 * 75))
    monkeypatch.setattr(snmp_agent, "_raw", lambda: {})
    t = snmp_agent.mib(proc=str(proc), pool="/mnt/storage", started=0.0, host_root=str(tmp_path))
    descr = {k[-1]: str(v) for k, v in t.items() if k[:-1] == snmp_agent.HR + (2, 3, 1, 3)}
    assert descr == {1: "Physical memory", 2: "/mnt/storage/media", 3: "/mnt/storage/tank"}
