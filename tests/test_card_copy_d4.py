"""Card copy as a tester found it on a generic Linux host (#68): the button's folder, the partition
with the photos, the camera's clock, and the card's own housekeeping files."""

import os
import types

from backend.services import copy_engine as ce


def test_the_folder_defaults_to_the_pool_where_unraids_is_missing(monkeypatch):
    monkeypatch.setattr(ce, "POOL_PATH", "/mnt/storage")
    monkeypatch.setattr(ce.os, "access", lambda p, mode: True)  # Kiboto may write the pool: never the test machine's
    real_isdir = os.path.isdir
    monkeypatch.setattr(ce.os.path, "isdir", lambda p: False if p == "/mnt/user" else real_isdir(p))
    assert ce.copy_dest(None) == "/mnt/storage"
    assert ce.copy_dest("") == "/mnt/storage"
    assert ce.copy_dest("/mnt/user/") == "/mnt/storage"
    assert ce.copy_dest("/mnt/storage/Photos") == "/mnt/storage/Photos"


def test_unraids_folder_stays_where_it_exists(monkeypatch):
    monkeypatch.setattr(ce.os.path, "isdir", lambda p: True)
    assert ce.copy_dest("/mnt/user/") == "/mnt/user/"


def _part(root, dev, name, sectors):
    d = root / "block" / dev / name
    d.mkdir(parents=True)
    (d / "partition").write_text("1\n")
    (d / "size").write_text(f"{sectors}\n")


def test_the_largest_partition_is_the_photos(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "HOST_SYS", str(tmp_path))
    _part(tmp_path, "sda", "sda1", 409600)  # a Mac's 200 MB EFI partition
    _part(tmp_path, "sda", "sda2", 62_000_000)  # the exFAT data
    (tmp_path / "block" / "sda" / "size").write_text("62500000\n")
    assert ce._card_partition("sda") == "sda2"
    (tmp_path / "block" / "sdb").mkdir()
    assert ce._card_partition("sdb") == "sdb"  # a card without partitions


def _boot(path, kind):
    sector = bytearray(512)
    if kind == "exfat":
        sector[3:11] = b"EXFAT   "
    elif kind == "fat32":
        sector[82:90] = b"FAT32   "
    elif kind == "fat16":
        sector[54:62] = b"FAT16   "
    path.write_bytes(bytes(sector))


def test_fat_and_exfat_are_told_apart_from_the_rest(tmp_path):
    for kind, want in (("exfat", "exfat"), ("fat32", "vfat"), ("fat16", "vfat"), ("ext4", "")):
        img = tmp_path / kind
        _boot(img, kind)
        assert ce._fat_kind(str(img)) == want
    assert ce._fat_kind(str(tmp_path / "missing")) == ""


def test_a_camera_card_is_read_in_the_servers_time_zone(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ce, "CARD_MOUNT", str(tmp_path / "mnt"))
    monkeypatch.setattr(ce, "run_bounded", lambda cmd, **kw: calls.append(cmd) or types.SimpleNamespace(returncode=0))
    exfat, ext4 = tmp_path / "exfat", tmp_path / "ext4"
    _boot(exfat, "exfat")
    _boot(ext4, "ext4")
    ce._mount_card_here(str(exfat), 660)  # Sydney in summer
    ce._mount_card_here(str(ext4), 660)
    ce._mount_card_here(str(exfat), 0)
    ce._mount_card_here(str(exfat), 99999)
    opts = [c[c.index("-o") + 1] for c in calls]
    assert opts[0].endswith(",time_offset=660")
    assert "time_offset" not in opts[1] and "time_offset" not in opts[2]
    assert opts[3].endswith(",time_offset=840")  # clamped to a real zone
    assert all(c[:2] == ["mount", "-r"] for c in calls)


def test_the_door_is_told_the_offset():
    from backend.services import host_door

    with open(host_door.__file__, encoding="utf-8") as f:
        src = f.read()
    assert '"copy.mount": Operation(_card, {"device": TEXT, "offset": (int,)}' in src


def test_only_the_photos_and_videos_are_planned(tmp_path):
    card, dst = tmp_path / "card", tmp_path / "dst"
    (card / "DCIM" / "100GOPRO").mkdir(parents=True)
    (card / "MISC").mkdir()
    (card / ".Spotlight-V100").mkdir()
    (card / "System Volume Information").mkdir()
    for rel in (
        "DCIM/100GOPRO/GX014301.MP4",
        "DCIM/100GOPRO/GX014301.LRV",
        "DCIM/100GOPRO/GOPR4300.JPG",
        "DCIM/100GOPRO/GX014301.THM",
        "Get_started_with_GoPro.url",
        "MISC/version.db",
        "MISC/fw.log",
        "MISC/settings.bk",
        ".Spotlight-V100/store.db",
        "System Volume Information/IndexerVolumeGuid",
        "DCIM/100GOPRO/._GOPR4300.JPG",
    ):
        (card / rel).write_bytes(b"x")
    dst.mkdir()
    entries, _ = ce.build_copy_plan(str(card), str(dst), use_exif=False)
    names = sorted(os.path.basename(e[0]) for e in entries)
    assert names == ["GOPR4300.JPG", "GX014301.LRV", "GX014301.MP4", "GX014301.THM"]


def test_the_saved_unraid_folder_is_replaced_on_a_host_without_it(tmp_path, monkeypatch):
    from backend.api import system

    cfg = tmp_path / "button_state.json"
    cfg.write_text('{"enabled": false, "dest": "/mnt/user/"}')
    monkeypatch.setattr(system, "BUTTON_CFG_FILE", str(cfg))
    monkeypatch.setattr(ce, "POOL_PATH", "/mnt/storage")
    monkeypatch.setattr(ce.os, "access", lambda p, mode: True)  # never the test machine: Kiboto may write the pool
    real_isdir = os.path.isdir
    monkeypatch.setattr(ce.os.path, "isdir", lambda p: False if p == "/mnt/user" else real_isdir(p))
    assert system._load_buttons()["dest"] == "/mnt/storage"


def test_on_kiboto_os_photos_go_to_a_shared_folder_kiboto_may_write(monkeypatch, tmp_path):
    """There the storage folder is root's: every import from a card or a USB disk failed with
    "Permission denied: /mnt/storage/2026"."""
    from backend.hardware import pal_storage

    pool = tmp_path / "storage"
    family, start = pool / "tank" / "family", pool / "tank" / "storage"
    for folder in (family, start):
        folder.mkdir(parents=True)
    monkeypatch.setattr(ce, "POOL_PATH", str(pool))
    writable = {str(family), str(start)}
    monkeypatch.setattr(ce.os, "access", lambda p, mode: p in writable)
    shares = [
        types.SimpleNamespace(name="family", mountpoint=str(family)),
        types.SimpleNamespace(name="storage", mountpoint=str(start)),
    ]
    monkeypatch.setattr(
        pal_storage, "get_storage_platform", lambda: types.SimpleNamespace(list_shares=lambda: list(shares))
    )
    assert ce.copy_dest(None) == str(start)  # the shared folder every install starts with
    assert ce.copy_dest(str(pool) + "/") == str(start)  # the pool, as saved by default
    assert ce.copy_dest(str(family)) == str(family)  # a folder someone chose stays
    writable.discard(str(start))
    assert ce.copy_dest("") == str(family)  # else the first one Kiboto may write
    writable.clear()
    assert ce.copy_dest("") == str(pool)  # none: the pool, and the copy says why it failed
    monkeypatch.setattr(
        pal_storage,
        "get_storage_platform",
        lambda: types.SimpleNamespace(list_shares=lambda: (_ for _ in ()).throw(OSError("x"))),
    )
    assert ce.default_dest() == str(pool)
