"""Looking into pools that are not in use: read-only, and closed again."""

import json
import os

import pytest

from backend.hardware.pal import pool_probe

ZPOOL_IMPORT = """   pool: tank
     id: 16563031430006869722
  state: ONLINE
 action: The pool can be imported using its name or numeric identifier.
 config:

        tank        ONLINE
          mirror-0  ONLINE
            vdb     ONLINE
            vdc     ONLINE

   pool: old pool; rm -rf /
     id: 123
  state: ONLINE

   pool: attic
     id: 42
  state: DEGRADED
"""
LSBLK = {
    "blockdevices": [
        {
            "path": "/dev/vda",
            "fstype": None,
            "uuid": None,
            "label": None,
            "mountpoints": [None],
            "children": [
                {"path": "/dev/vda1", "fstype": "ext4", "uuid": "aaaaaaaa-0000-4000-8000-000000000001", "label": None, "mountpoints": ["/"]},
                {"path": "/dev/vda15", "fstype": "vfat", "uuid": "1234-ABCD", "label": None, "mountpoints": ["/boot/efi"]},
            ],
        },
        {"path": "/dev/vdd", "fstype": "btrfs", "uuid": "0d68d8be-7771-40fb-bdc4-ea56c44ae2f6", "label": "media", "mountpoints": [None]},
        {"path": "/dev/vde", "fstype": "btrfs", "uuid": "0d68d8be-7771-40fb-bdc4-ea56c44ae2f6", "label": "media", "mountpoints": [None]},
        {"path": "/dev/vdf", "fstype": "ext4", "uuid": "de66aec1-24ed-4727-884f-65c065477f92", "label": None, "mountpoints": []},
        {"path": "/dev/vdg", "fstype": "swap", "uuid": "bbbbbbbb-0000-4000-8000-000000000002", "label": None, "mountpoints": [None]},
        {"path": "/dev/vdh", "fstype": "ext4", "uuid": "$(reboot)", "label": "x", "mountpoints": [None]},
        {"path": "/dev/vdb", "fstype": None, "uuid": None, "label": None, "mountpoints": [None], "children": [
            {"path": "/dev/vdb1", "fstype": "zfs_member", "uuid": "16563031430006869722", "label": "tank", "mountpoints": [None]}]},
    ]
}  # fmt: skip


class Storage:
    def __init__(self):
        self.seen, self.fails, self.lsblk, self.zpool = [], set(), json.dumps(LSBLK), ZPOOL_IMPORT
        self.altroot, self.prefixed = "", True

    def __call__(self, cmd):
        self.seen.append(cmd)
        if " ".join(cmd[:2]) in self.fails or cmd[0] in self.fails:
            if "-l" not in cmd:
                return 1, "", "refused"
        if cmd == ["zpool", "import"]:
            return 0, self.zpool, ""
        if cmd[0] == "lsblk":
            return 0, self.lsblk, ""
        if cmd[:2] == ["zpool", "import"] and "-R" in cmd:
            self.altroot = cmd[cmd.index("-R") + 1]
        if cmd[:2] == ["zfs", "get"]:  # as ZFS answers for a pool imported with -R: under that folder
            return 0, (self.altroot if self.prefixed else "") + "/mnt/storage/tank\n", ""
        return 0, "", ""


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(pool_probe, "PROBE_ROOT", str(tmp_path / "probe"))
    return Storage()


def test_what_is_here_and_not_in_use(storage):
    assert pool_probe.candidates(storage) == [
        {"kind": "zfs", "name": "tank", "id": "16563031430006869722"},
        {"kind": "zfs", "name": "attic", "id": "42"},  # the one with a name no pool can have is left out
        {"kind": "btrfs", "name": "media", "id": "0d68d8be-7771-40fb-bdc4-ea56c44ae2f6"},  # two drives, one pool
        {"kind": "ext4", "name": "de66aec1", "id": "de66aec1-24ed-4727-884f-65c065477f92"},
    ]


def test_nothing_to_look_into(storage):
    storage.zpool, storage.lsblk = "", "not json"
    assert pool_probe.candidates(storage) == []
    storage.fails = {"zpool", "lsblk"}
    assert pool_probe.candidates(storage) == []


def test_a_zfs_pool_is_opened_read_only_looked_at_and_closed(storage, tmp_path):
    seen_at = []
    got = pool_probe.look_into(
        {"kind": "zfs", "name": "tank", "id": "16563031430006869722"},
        storage,
        lambda root: seen_at.append(root) or "found",
    )
    spot = str(tmp_path / "probe" / "16563031430006869722")
    assert got == "found" and seen_at == [os.path.join(spot, "mnt/storage/tank")]
    assert storage.seen == [
        [
            "zpool",
            "import",
            "-f",
            "-N",
            "-o",
            "readonly=on",
            "-o",
            "cachefile=none",
            "-R",
            spot,
            "16563031430006869722",
        ],
        ["zfs", "get", "-H", "-o", "value", "mountpoint", "tank"],
        ["zfs", "mount", "tank"],
        ["zpool", "export", "tank"],
    ]
    assert not os.path.exists(spot)


def test_a_mountpoint_without_the_folder_in_front_is_found_too(storage, tmp_path):
    storage.prefixed = False
    seen = []
    got = pool_probe.look_into({"kind": "zfs", "name": "tank", "id": "7"}, storage, lambda r: seen.append(r) or "ok")
    assert got == "ok" and seen == [os.path.join(str(tmp_path / "probe" / "7"), "mnt/storage/tank")]


def test_a_zfs_pool_is_closed_even_when_reading_it_fails(storage):
    def read(root):
        raise OSError("unreadable")

    with pytest.raises(OSError):
        pool_probe.look_into({"kind": "zfs", "name": "tank", "id": "1"}, storage, read)
    assert storage.seen[-1] == ["zpool", "export", "tank"]


def test_a_zfs_pool_that_does_not_open_or_mount_is_left(storage):
    storage.fails = {"zpool import"}
    assert pool_probe.look_into({"kind": "zfs", "name": "tank", "id": "1"}, storage, lambda r: "x") is None
    assert ["zpool", "export", "tank"] not in storage.seen  # it never opened
    storage.fails, storage.seen = {"zfs mount", "zpool export"}, []
    assert pool_probe.look_into({"kind": "zfs", "name": "tank", "id": "1"}, storage, lambda r: "x") is None
    assert storage.seen[-1] == ["zpool", "export", "tank"]  # tried, and said in the log when it stays open


def test_an_ext4_file_system_is_mounted_without_its_journal_and_unmounted(storage, tmp_path):
    uuid = "de66aec1-24ed-4727-884f-65c065477f92"
    got = pool_probe.look_into({"kind": "ext4", "name": "docs", "id": uuid}, storage, lambda root: root)
    spot = str(tmp_path / "probe" / uuid.replace("-", ""))
    assert got == spot
    assert storage.seen == [
        ["mount", "-t", "ext4", "-o", "ro,noload,nosuid,nodev,noexec", f"UUID={uuid}", spot],
        ["umount", spot],
    ]


def test_a_btrfs_pool_is_mounted_without_replaying_its_log(storage, tmp_path):
    uuid = "0d68d8be-7771-40fb-bdc4-ea56c44ae2f6"
    pool_probe.look_into({"kind": "btrfs", "name": "media", "id": uuid}, storage, lambda root: root)
    spot = str(tmp_path / "probe" / uuid.replace("-", ""))
    assert storage.seen == [
        ["btrfs", "device", "scan"],
        ["mount", "-t", "btrfs", "-o", "ro,rescue=nologreplay,nosuid,nodev,noexec", f"UUID={uuid}", spot],
        ["umount", spot],
    ]


def test_a_file_system_that_does_not_mount_is_left_and_a_stuck_one_is_let_go(storage, tmp_path):
    uuid = "0d68d8be-7771-40fb-bdc4-ea56c44ae2f6"
    storage.fails = {"mount"}
    assert pool_probe.look_into({"kind": "btrfs", "name": "media", "id": uuid}, storage, lambda r: "x") is None
    mounts = [c for c in storage.seen if c[0] == "mount"]
    assert [m[4] for m in mounts] == [
        "ro,rescue=nologreplay,nosuid,nodev,noexec",
        "ro,nosuid,nodev,noexec",
    ]  # tried plain too
    assert not [c for c in storage.seen if c[0] == "umount"]
    storage.fails, storage.seen = {"umount"}, []
    assert pool_probe.look_into({"kind": "ext4", "name": "docs", "id": uuid}, storage, lambda r: "x") == "x"
    assert [c[:2] for c in storage.seen[-2:]] == [
        ["umount", str(tmp_path / "probe" / uuid.replace("-", ""))],
        ["umount", "-l"],
    ]
