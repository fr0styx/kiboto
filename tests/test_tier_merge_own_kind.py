"""A shared folder that is a ZFS dataset or a btrfs subvolume can be merged: Kiboto makes every new
shared folder on those pools as one, and before, all of them were refused as "a mount of its own"."""

import os
from types import SimpleNamespace

import pytest

from backend.services import host_basics, tier_merge


def mounts(*rows):
    return lambda: [{"at": at, "tags": "", "fs": fs, "source": source} for at, fs, source in rows]


def test_a_plain_folder_a_dataset_and_a_subvolume_can_be_merged(tmp_path, monkeypatch):
    folder = tmp_path / "films"
    folder.mkdir()
    monkeypatch.setattr(tier_merge, "_mounts", mounts(("/", "ext4", "/dev/vda1")))
    assert tier_merge.own_kind(str(folder)) == "folder"
    monkeypatch.setattr(tier_merge, "_mounts", mounts(("/", "ext4", "/dev/vda1"), (str(folder), "zfs", "tank/films")))
    assert tier_merge.own_kind(str(folder)) == "dataset"
    assert tier_merge._dataset_at(str(folder)) == "tank/films"

    monkeypatch.setattr(tier_merge, "_mounts", mounts(("/", "btrfs", "/dev/vdb")))
    monkeypatch.setattr(tier_merge.os.path, "ismount", lambda p: p == str(folder))
    real_stat = os.stat
    monkeypatch.setattr(
        tier_merge.os,
        "stat",
        lambda p, *a, **k: (
            SimpleNamespace(st_ino=256, st_mode=real_stat(p).st_mode) if p == str(folder) else real_stat(p, *a, **k)
        ),
    )
    assert tier_merge.own_kind(str(folder)) == "subvolume"
    monkeypatch.setattr(tier_merge, "_mounts", mounts(("/", "ext4", "/dev/vdb")))
    assert tier_merge.own_kind(str(folder)) == ""  # a mount boundary that is no btrfs subvolume


@pytest.mark.parametrize("kind", ["nfs4", "fuse.mergerfs", "zfs-without-source"])
def test_a_mount_of_another_kind_a_mount_inside_or_a_link_is_not_merged(tmp_path, monkeypatch, kind):
    folder = tmp_path / "films"
    folder.mkdir()
    fs, source = ("zfs", "") if kind == "zfs-without-source" else (kind, "server:/x")
    monkeypatch.setattr(tier_merge, "_mounts", mounts(("/", "ext4", "/dev/vda1"), (str(folder), fs, source)))
    assert tier_merge.own_kind(str(folder)) == ""
    monkeypatch.setattr(
        tier_merge, "_mounts", mounts(("/", "ext4", "/dev/vda1"), (str(folder / "inner"), "zfs", "t/i"))
    )
    assert tier_merge.own_kind(str(folder)) == ""
    link = tmp_path / "link"
    link.symlink_to(folder)
    assert tier_merge.own_kind(str(link)) == ""
    assert tier_merge.own_kind(str(tmp_path / "missing")) == ""


@pytest.fixture
def zfs(monkeypatch):
    seen, answers = [], {}

    def run(cmd, timeout=20):
        seen.append(cmd)
        return answers.get(tuple(cmd[:3]), (0, ""))

    monkeypatch.setattr(host_basics, "run", run)
    return seen, answers


def test_a_dataset_moves_by_its_mount_point_and_comes_back_as_it_was(tmp_path, zfs):
    seen, answers = zfs
    path, fast = str(tmp_path / "films"), str(tmp_path / ".kiboto-tier" / "films")
    merge = {"own": "dataset", "dataset": "tank/films"}
    answers[("zfs", "get", "-H")] = (0, "inherited from tank\n")
    tier_merge._move_away(merge, path, fast)
    assert seen[-1] == ["zfs", "set", f"mountpoint={fast}", "tank/films"] and merge["mount_was"] == "inherited"
    os.mkdir(path)  # the placeholder while merged
    tier_merge._move_back(merge, path, fast)
    assert seen[-1] == ["zfs", "inherit", "mountpoint", "tank/films"] and not os.path.exists(path)

    answers[("zfs", "get", "-H")] = (0, "local\n")
    tier_merge._move_away(merge, path, fast)
    tier_merge._move_back(merge, path, fast)
    assert merge["mount_was"] == "local" and seen[-1] == ["zfs", "set", f"mountpoint={path}", "tank/films"]


def test_a_dataset_zfs_will_not_move_is_said(tmp_path, zfs):
    seen, answers = zfs
    answers[("zfs", "set", f"mountpoint={tmp_path}/f")] = (1, "cannot unmount: pool or dataset is busy")
    with pytest.raises(OSError, match="busy"):
        tier_merge._move_away({"own": "dataset", "dataset": "tank/films"}, str(tmp_path / "films"), str(tmp_path / "f"))
    answers[("zfs", "inherit", "mountpoint")] = (1, "")
    (tmp_path / "films").mkdir()
    with pytest.raises(OSError, match="not moved back"):
        tier_merge._move_back(
            {"own": "dataset", "dataset": "tank/films", "mount_was": "inherited"}, str(tmp_path / "films"), "/x"
        )


def test_a_folder_or_subvolume_moves_by_one_rename(tmp_path):
    path, fast = tmp_path / "films", tmp_path / "hidden"
    path.mkdir()
    (path / "a.txt").write_text("a")
    tier_merge._move_away({"own": "subvolume"}, str(path), str(fast))
    assert (fast / "a.txt").exists() and not path.exists()
    path.mkdir()
    tier_merge._move_back({"own": "subvolume"}, str(path), str(fast))
    assert (path / "a.txt").exists() and not fast.exists()
