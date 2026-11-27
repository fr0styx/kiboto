"""A shared folder that shows two pools as one (data tiering on Kiboto's own pools, 19 Nov 2026).
The mounting itself was tried with throwaway containers on a real machine (the folder showed on the
host and in a second container, a killed merge came back); here the steps around it are checked:
what is renamed, what is written for the container, and that a failure puts the folder back."""

import os

import pytest

from backend import merged_folders
from backend.services import tier_merge as tm

ME = {
    "Config": {"Image": "ghcr.io/example/kiboto:sha-abc"},
    "Mounts": [
        {"Source": "/srv/storage", "Destination": "/mnt/storage"},
        {"Source": "/host/appdata/kiboto", "Destination": "/data"},
    ],
}


@pytest.fixture(autouse=True)
def box(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    share = storage / "ssd" / "Films"
    share.mkdir(parents=True)
    (storage / "hdd").mkdir()
    (share / "a.mkv").write_text("film")
    os.chmod(share, 0o775)
    info = tmp_path / "mountinfo"
    info.write_text(f"30 20 0:30 / {storage} rw,relatime master:1 - btrfs /dev/sda rw\n")
    fuse = tmp_path / "fuse"
    fuse.write_text("")
    monkeypatch.setattr(merged_folders, "STATE_FILE", str(tmp_path / "data" / "tier_merge.json"))
    monkeypatch.setattr(tm, "CONF_DIR", str(tmp_path / "data" / "merge"))
    monkeypatch.setattr(tm, "MOUNTINFO", str(info))
    monkeypatch.setattr(tm, "FUSE", str(fuse))
    monkeypatch.setattr(tm, "MOUNT_WAIT_SECS", 0.3)
    monkeypatch.setattr(tm, "UNMOUNT_WAIT_SECS", 0.3)
    monkeypatch.setattr(tm.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(tm, "_asked", {"at": 0.0, "said": None})
    (tmp_path / "data").mkdir()
    me = {
        "Config": ME["Config"],
        "Mounts": [
            {"Source": "/srv/storage", "Destination": str(storage)},
            {"Source": "/host/appdata/kiboto", "Destination": str(tmp_path / "data")},
        ],
    }
    state = {"calls": [], "helper": None, "mounts_come_up": True, "smb": None, "share": share, "storage": storage}

    def mount_lines():
        return [
            f"40 30 0:55 / {m['path']} rw shared:9 - fuse.mergerfs kiboto-tier rw\n" for m in merged_folders.merges()
        ]

    def docker(method, path, body=None, headers=None):
        state["calls"].append((method, path, body, headers))
        base = info.read_text().splitlines(keepends=True)[:1]
        if method == "GET" and path.endswith(f"/{tm.CONTAINER}/json"):
            return (200, state["helper"]) if state["helper"] else (404, None)
        if method == "GET" and "samba" in path:
            return (200, {"Mounts": state["smb"]}) if state["smb"] is not None else (404, None)
        if method == "GET":
            return 200, me
        if method == "POST" and "/create" in path:
            state["helper"] = {"State": {"Running": False}, "Config": {"Labels": body["Labels"]}, "made": body}
            return 201, {}
        if method == "POST" and path.endswith("/start"):
            state["helper"]["State"]["Running"] = True
            info.write_text("".join(base + (mount_lines() if state["mounts_come_up"] else [])))
            return 204, {}
        if method == "POST" and "/stop" in path:
            info.write_text("".join(base))  # asked to stop, it unmounts what it mounted
            return 204, {}
        if method == "DELETE":
            state["helper"] = None
        return 204, {}

    monkeypatch.setattr(tm, "_docker", docker)
    return state


def test_the_two_sides_are_hidden_folders_on_each_pool():
    assert tm.sides("/mnt/storage/ssd/Films/", "/mnt/storage/hdd") == (
        "/mnt/storage/ssd/.kiboto-tier/Films",
        "/mnt/storage/hdd/.kiboto-tier/Films",
    )


def test_what_the_system_lacks_is_named(box, monkeypatch):
    path = str(box["share"])
    assert tm.missing(path) == ""
    box["smb"] = [{"Destination": str(box["storage"]), "Propagation": "rprivate"}]
    tm._asked["said"] = None
    assert tm.missing(path) == "smb_not_shared"  # the SMB container would not see the merge
    box["smb"] = [{"Destination": str(box["storage"]), "Propagation": "rslave"}]
    tm._asked["said"] = None
    assert tm.missing(path) == ""
    box["smb"] = [{"Destination": "/somewhere/else", "Propagation": "rslave"}]
    tm._asked["said"] = None
    assert tm.missing(path) == "smb_not_shared"
    with open(tm.MOUNTINFO, "w") as f:
        f.write(f"30 20 0:30 / {box['storage']} rw,relatime - btrfs /dev/sda rw\n")
    assert tm.missing(path) == "not_shared"  # the install file without shared mounts
    monkeypatch.setattr(tm, "FUSE", "/nowhere/fuse")
    assert tm.missing(path) == "no_fuse"
    monkeypatch.setattr(tm.shutil, "which", lambda name: None)
    assert tm.missing(path) == "no_tool"


def test_the_helper_program_mounts_each_folder_and_unmounts_when_asked():
    kept = [
        {"path": "/p1/My Films", "fast": "/p1/.kiboto-tier/My Films", "slow": "/p2/.kiboto-tier/My Films"},
        {"path": "/p1/It's", "fast": "/p1/.kiboto-tier/It's", "slow": "/p2/.kiboto-tier/It's"},
    ]
    text = tm.script(kept)
    assert text.startswith("#!/bin/sh\n") and text.rstrip().endswith("done")
    # one merge's program dying ends the container with an error: Docker starts it again, all mounted anew
    assert 'kill -0 "$p" 2>/dev/null || stop 1' in text and "trap 'stop 0' TERM INT" in text
    assert "merge '/p1/.kiboto-tier/My Films' '/p2/.kiboto-tier/My Films' '/p1/My Films'" in text
    assert """merge '/p1/.kiboto-tier/It'"'"'s' '/p2/.kiboto-tier/It'"'"'s' '/p1/It'"'"'s'""" in text
    assert 'umount -l "$3"' in text and f'{tm.TOOL} -f -o {tm.OPTIONS} "$1:$2" "$3" &' in text
    assert "trap " in text and "TERM" in text
    assert "category.create=ff" in tm.OPTIONS and "cache.files=off" in tm.OPTIONS  # new files on the fast side


def test_a_folder_becomes_a_merged_one_with_one_rename(box):
    share = box["share"]
    made = tm.add("Films", str(share), str(box["storage"] / "hdd"), "pool-hdd")
    fast, slow = box["storage"] / "ssd" / ".kiboto-tier" / "Films", box["storage"] / "hdd" / ".kiboto-tier" / "Films"
    assert (made["fast"], made["slow"], made["slow_pool"]) == (str(fast), str(slow), "pool-hdd")
    assert (fast / "a.mkv").read_text() == "film"  # its own files, moved by a rename
    assert oct(os.stat(share).st_mode & 0o777) == "0o0"  # nobody writes here while the merge is not mounted
    assert oct(os.stat(slow).st_mode & 0o777) == "0o775" and os.listdir(slow) == []
    assert merged_folders.of(str(share))["name"] == "Films" and tm.status()[0]["mounted"] is True
    assert merged_folders.held_on(str(box["storage"] / "hdd")) == ["Films"]
    assert merged_folders.held_on(str(box["storage"] / "ssd")) == ["Films"]
    assert merged_folders.held_on("/mnt/other") == [] and merged_folders.held_on("") == []
    want = box["helper"]["made"]
    assert want["Image"] == "ghcr.io/example/kiboto:sha-abc" and want["Cmd"] == [f"/conf/{tm.CONF_NAME}"]
    host = want["HostConfig"]
    assert host["NetworkMode"] == "none" and host["CapAdd"] == ["SYS_ADMIN"]
    assert host["Devices"][0]["PathOnHost"] == "/dev/fuse" and host["RestartPolicy"] == {"Name": "unless-stopped"}
    assert host["Binds"] == ["/host/appdata/kiboto/merge:/conf:ro"]
    # the pools at the path Kiboto knows them by; what is mounted there is passed on to the host
    assert host["Mounts"] == [
        {
            "Type": "bind",
            "Source": "/srv/storage",
            "Target": str(box["storage"]),
            "BindOptions": {"Propagation": "rshared"},
        }
    ]
    created = [c for c in box["calls"] if c[0] == "POST" and "/create" in c[1]]
    assert len(created) == 1 and created[0][3] == tm.ELEVATED
    with open(os.path.join(tm.CONF_DIR, tm.CONF_NAME), encoding="utf-8") as f:
        assert f"merge {fast} {slow} {share}" in f.read()
    assert tm.add("Films", str(share), str(box["storage"] / "hdd"), "pool-hdd") == merged_folders.of(str(share))  # once


def test_when_the_merge_does_not_come_up_the_folder_is_put_back(box):
    box["mounts_come_up"] = False
    share = box["share"]
    with pytest.raises(tm.MergeError) as e:
        tm.add("Films", str(share), str(box["storage"] / "hdd"), "pool-hdd")
    assert e.value.key == "no_mount"
    assert (share / "a.mkv").read_text() == "film" and oct(os.stat(share).st_mode & 0o777) == "0o775"
    assert not (box["storage"] / "ssd" / ".kiboto-tier" / "Films").exists()
    assert merged_folders.merges() == [] and box["helper"] is None  # no merge kept, no container left


def test_what_cannot_be_merged_is_refused_before_anything_moves(box, tmp_path):
    share, hdd = box["share"], str(box["storage"] / "hdd")
    link = box["storage"] / "ssd" / "Link"
    os.symlink(share, link)
    odd = box["storage"] / "ssd" / "a:b"
    odd.mkdir()
    for path, slow, key in (
        (str(link), hdd, "not_plain"),
        (str(odd), hdd, "bad_name"),
        (str(share), str(box["storage"] / "ssd"), "bad_sides"),  # the slower pool is its own pool
        (str(share), str(tmp_path / "nowhere"), "bad_sides"),
    ):
        with pytest.raises(tm.MergeError) as e:
            tm.add("x", path, slow, "p")
        assert e.value.key == key, path
    (box["storage"] / "ssd" / ".kiboto-tier" / "Films").mkdir(parents=True)  # something is in the way already
    with pytest.raises(tm.MergeError) as e:
        tm.add("Films", str(share), hdd, "p")
    assert e.value.key == "bad_sides" and (share / "a.mkv").exists() and merged_folders.merges() == []
    assert not [c for c in box["calls"] if c[0] == "POST"]


def test_turned_off_it_stays_merged_while_files_are_on_the_slow_side(box):
    share = box["share"]
    made = tm.add("Films", str(share), str(box["storage"] / "hdd"), "pool-hdd")
    with open(os.path.join(made["slow"], "old.mkv"), "w") as f:
        f.write("old")
    assert tm.remove_if_empty(str(share)) is False and merged_folders.of(str(share)) is not None
    os.remove(os.path.join(made["slow"], "old.mkv"))
    assert tm.remove_if_empty(str(share)) is True
    assert (share / "a.mkv").read_text() == "film" and oct(os.stat(share).st_mode & 0o777) == "0o775"
    assert merged_folders.merges() == [] and box["helper"] is None and not os.path.exists(made["slow"])
    assert not (box["storage"] / "ssd" / tm.HIDDEN).exists() and not (box["storage"] / "hdd" / tm.HIDDEN).exists()
    assert tm.remove_if_empty(str(share)) is True  # an ordinary folder: nothing to do


def test_the_container_is_made_again_only_when_the_folders_change(box):
    tm.add("Films", str(box["share"]), str(box["storage"] / "hdd"), "pool-hdd")
    box["calls"].clear()
    assert tm.ensure() == ""
    assert not [c for c in box["calls"] if c[0] in ("POST", "DELETE")]  # it runs and nothing changed: left alone
    box["helper"]["State"]["Running"] = False  # it ended: started again
    assert tm.ensure() == "" and [c[1].split("?")[0] for c in box["calls"] if c[0] == "POST"][-2:] == [
        "/containers/create",
        f"/containers/{tm.CONTAINER}/start",
    ]
    other = box["storage"] / "ssd" / "Photos"
    other.mkdir()
    box["calls"].clear()
    tm.add("Photos", str(other), str(box["storage"] / "hdd"), "pool-hdd")
    posts = [c[1].split("?")[0] for c in box["calls"] if c[0] == "POST"]
    assert posts == [f"/containers/{tm.CONTAINER}/stop", "/containers/create", f"/containers/{tm.CONTAINER}/start"]
    assert len(tm.status()) == 2 and all(m["mounted"] for m in tm.status())


def test_a_merge_that_is_listed_but_dead_is_not_mounted(box, monkeypatch):
    share = box["share"]
    tm.add("Films", str(share), str(box["storage"] / "hdd"), "pool-hdd")
    assert tm.mounted(str(share)) is True
    real = os.stat

    def dead(path, *a, **k):
        if str(path) == str(share):
            raise OSError(107, "Transport endpoint is not connected")
        return real(path, *a, **k)

    monkeypatch.setattr(tm.os, "stat", dead)
    assert tm.mounted(str(share)) is False and tm.status()[0]["mounted"] is False


def test_folders_emptied_by_hand_on_the_slow_side_do_not_keep_it_merged(box):
    share = box["share"]
    made = tm.add("Films", str(box["share"]), str(box["storage"] / "hdd"), "pool-hdd")
    os.makedirs(os.path.join(made["slow"], "2019", "summer"))
    with open(os.path.join(made["slow"], "2019", "summer", "old.mkv"), "w") as f:
        f.write("old")
    assert tm.remove_if_empty(str(share)) is False
    os.remove(os.path.join(made["slow"], "2019", "summer", "old.mkv"))  # the folders it was in stay
    assert tm.remove_if_empty(str(share)) is True
    assert merged_folders.merges() == [] and not os.path.exists(made["slow"])
