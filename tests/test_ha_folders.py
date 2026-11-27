"""High availability: the second NAS keeps chosen folders of the first one in step (the owner's
decisions of 19 Nov 2026: every night; into a shared folder of the same name; a file deleted on
the first NAS is kept 30 days). Two boxes are played by one process, as in test_ha_link.py. The
rule that matters most: the second NAS only replaces or puts away files it fetched itself."""

import copy
import os
import time

import pytest

from backend.services import ha_folders as hf
from backend.services import ha_link as ha

A, B = "http://192.168.1.10:8082", "http://192.168.1.20:8082"
DAY = 86400


class Net:
    def __init__(self, tmp_path, monkeypatch):
        self.dirs = {A: tmp_path / "first", B: tmp_path / "second"}
        self.shares = {A: {}, B: {}}
        for d in self.dirs.values():
            (d / "pool").mkdir(parents=True)
        self.patch, self.me, self.down = monkeypatch, A, False
        monkeypatch.setattr(ha, "my_name", lambda: "First NAS" if self.me == A else "Second NAS")
        monkeypatch.setattr(ha, "audit", lambda *a: None)
        monkeypatch.setattr(ha, "_seen", {})
        monkeypatch.setattr(hf, "_offers", {})
        monkeypatch.setattr(hf, "PIECE", 1000)
        monkeypatch.setattr(hf, "LINES", 2)
        monkeypatch.setattr(hf, "shares", lambda: dict(self.shares[self.me]))
        monkeypatch.setattr(hf, "make_share", self.make_share)
        self.on(A)

    def make_share(self, name):
        path = self.dirs[self.me] / "pool" / name
        path.mkdir(exist_ok=True)
        self.shares[self.me][name] = str(path)
        return str(path)

    def on(self, box):
        self.me = box
        self.patch.setattr(ha, "STATE_FILE", str(self.dirs[box] / "ha.json"))
        self.patch.setattr(hf, "DIR", str(self.dirs[box] / "ha"))

    def send(self, url, body):
        if self.down:
            raise ha.LinkError("unreachable", "The other NAS did not answer.")
        back, target = self.me, next(box for box in self.dirs if url.startswith(box))
        self.on(target)
        try:
            if url.endswith(ha.PAIR_PATH):
                return ha.accept_pairing(body["box_id"], body["name"], body["address"], body["public"], body["proof"])
            return ha.handle_call(copy.deepcopy(body))
        finally:
            self.on(back)

    def put(self, box, share, rel, text="data", mtime=1_700_000_000, mode=0o640):
        back = self.me
        self.on(box)
        root = self.shares[box].get(share) or self.make_share(share)
        self.on(back)
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)
        os.utime(path, (mtime, mtime))
        return path


@pytest.fixture
def net(tmp_path, monkeypatch):
    made = Net(tmp_path, monkeypatch)
    made.on(A)
    code = ha.new_code("ana")["code"]
    made.on(B)
    ha.pair_with(A, code, B, "ana", send=made.send)
    return made


def _tree(root):
    out = {}
    for at, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(at, name)
            with open(path) as f:
                out[os.path.relpath(path, root)] = f.read()
    return out


def test_a_folder_is_fetched_whole_into_a_shared_folder_of_the_same_name(net):
    net.put(A, "Films", "2019/a.mkv", "a" * 2500, mode=0o640)  # three pieces
    net.put(A, "Films", "b.txt", "bee")
    net.put(A, "Films", "empty.txt", "")
    os.symlink("/etc/passwd", os.path.join(net.shares[A]["Films"], "link"))  # links are not copied
    assert hf.choose(["Films"], send=net.send) == ["Films"] and hf.available(send=net.send) == ["Films"]
    out = hf.fetch_folder("Films", send=net.send)
    assert (
        out["fetched"],
        out["bytes"],
        out["same"],
        out["kept_yours"],
        out["removed"],
        out["errors"],
        out["why"],
    ) == (3, 2503, 0, 0, 0, [], "")
    there = net.shares[B]["Films"]
    assert _tree(there) == {"2019/a.mkv": "a" * 2500, "b.txt": "bee", "empty.txt": ""}
    st = os.stat(os.path.join(there, "2019", "a.mkv"))
    assert int(st.st_mtime) == 1_700_000_000 and oct(st.st_mode & 0o777) == "0o640"
    again = hf.fetch_folder("Films", send=net.send)
    assert (again["fetched"], again["same"]) == (0, 3)  # nothing changed: nothing travels twice
    net.on(A)
    assert [n for n in os.listdir(hf.DIR) if n.startswith("tree-")] == []  # the first NAS kept no list lying around


def test_folders_a_fetch_makes_are_like_the_shared_folder(net, monkeypatch):
    net.put(A, "Films", "2019/summer/a.mkv", "a")
    net.put(A, "Films", "2019/b.mkv", "b")
    there = net.make_share("Films")
    os.chmod(there, 0o2770)  # as a shared folder is: its group may write, new files keep the group
    owned = []
    monkeypatch.setattr(hf.os, "geteuid", lambda: 0)
    monkeypatch.setattr(hf.os, "chown", lambda path, uid, gid: owned.append((os.path.relpath(path, there), uid, gid)))
    hf.choose(["Films"], send=net.send)
    assert hf.fetch_folder("Films", send=net.send)["fetched"] == 2
    for folder in ("2019", "2019/summer"):
        assert oct(os.stat(os.path.join(there, folder)).st_mode & 0o7777) == "0o2770", folder
    like = os.stat(there)
    made = [o for o in owned if not o[0].endswith(hf.PART)]
    assert sorted(made) == [("2019", like.st_uid, like.st_gid), ("2019/summer", like.st_uid, like.st_gid)]
    # a folder that is there keeps what it has
    os.chmod(os.path.join(there, "2019"), 0o700)
    net.put(A, "Films", "2019/c.mkv", "c")
    assert hf.fetch_folder("Films", send=net.send)["fetched"] == 1
    assert oct(os.stat(os.path.join(there, "2019")).st_mode & 0o7777) == "0o700"


def test_a_changed_file_is_fetched_again_and_a_deleted_one_is_kept_for_a_while(net):
    net.put(A, "Films", "a.txt", "one")
    net.put(A, "Films", "gone.txt", "soon gone")
    hf.fetch_folder("Films", send=net.send, now=1_800_000_000)
    net.put(A, "Films", "a.txt", "two, longer", mtime=1_700_000_500)
    os.remove(os.path.join(net.shares[A]["Films"], "gone.txt"))
    out = hf.fetch_folder("Films", send=net.send, now=1_800_000_000 + DAY)
    assert (out["fetched"], out["removed"], out["kept_yours"]) == (1, 1, 0)
    there = net.shares[B]["Films"]
    day = time.strftime("%Y-%m-%d", time.localtime(1_800_000_000 + DAY))
    assert _tree(there) == {"a.txt": "two, longer", f"{hf.REMOVED}/{day}/gone.txt": "soon gone"}
    # 30 days later it goes; one day before that it is still there
    assert hf.prune_removed(there, now=1_800_000_000 + DAY + (hf.KEEP_REMOVED_DAYS - 1) * DAY) == 0
    out = hf.fetch_folder("Films", send=net.send, now=1_800_000_000 + (hf.KEEP_REMOVED_DAYS + 3) * DAY)
    assert _tree(there) == {"a.txt": "two, longer"} and out["removed"] == 0


def test_the_second_nas_never_touches_files_of_its_own(net):
    net.put(A, "Photos", "same-name.jpg", "the first NAS's picture")
    net.put(A, "Photos", "shared.jpg", "fetched, then edited on the second NAS")
    mine = net.put(B, "Photos", "same-name.jpg", "the second NAS's own picture", mtime=1_600_000_000)
    own = net.put(B, "Photos", "only-here.jpg", "only on the second NAS")
    out = hf.fetch_folder("Photos", send=net.send)
    assert (out["fetched"], out["kept_yours"]) == (1, 1)
    with open(mine) as f:
        assert f.read() == "the second NAS's own picture"  # not replaced
    edited = os.path.join(net.shares[B]["Photos"], "shared.jpg")
    with open(edited, "w") as f:
        f.write("changed here")
    net.put(A, "Photos", "shared.jpg", "a newer one on the first", mtime=1_700_000_900)
    os.remove(os.path.join(net.shares[A]["Photos"], "same-name.jpg"))
    out = hf.fetch_folder("Photos", send=net.send)
    with open(edited) as f:
        assert f.read() == "changed here"  # someone changed it here since it was fetched: left alone
    assert out["kept_yours"] == 1 and out["removed"] == 0
    assert os.path.exists(mine) and os.path.exists(own)  # gone on the first, but it was never fetched: it stays
    os.remove(os.path.join(net.shares[A]["Photos"], "shared.jpg"))
    out = hf.fetch_folder("Photos", send=net.send)
    assert out["removed"] == 0 and os.path.exists(edited)  # and an edited copy is not put away either


def test_the_first_nas_hands_out_only_files_inside_its_shared_folders(net):
    net.put(A, "Films", "a.txt", "one")
    secret = net.dirs[A] / "secret.txt"
    secret.write_text("not shared")
    os.symlink(str(secret), os.path.join(net.shares[A]["Films"], "way-out.txt"))
    for rel in ("../secret.txt", "/etc/passwd", "a/../../secret.txt", "", ".", f"{hf.REMOVED}/x", "way-out.txt"):
        with pytest.raises(ha.LinkError) as e:
            ha.call("file_piece", {"name": "Films", "rel": rel, "offset": 0}, send=net.send)
        assert e.value.key == "refused", rel
    with pytest.raises(ha.LinkError):
        ha.call("file_piece", {"name": "NoSuchShare", "rel": "a.txt", "offset": 0}, send=net.send)
    with pytest.raises(ha.LinkError):
        ha.call("tree_begin", {"name": "NoSuchShare"}, send=net.send)
    net.on(A)
    with pytest.raises(ha.LinkError):
        ha.call("folders_list", send=net.send)  # the second NAS hands nothing out


def test_kibotos_own_data_in_appdata_is_never_listed_sent_or_written(net, monkeypatch):
    import backend.fsutil as fsutil

    net.put(A, "appdata", "plex/Preferences.xml", "<prefs/>")
    net.put(A, "appdata", "kiboto/data/keys.json", "first NAS keys")
    net.put(B, "appdata", "kiboto/data/users.db", "second NAS people")
    ours = [os.path.realpath(os.path.join(net.shares[box]["appdata"], "kiboto")) for box in (A, B)]
    monkeypatch.setattr(fsutil, "protected_dirs", lambda: ours)
    hf.choose(["appdata"], send=net.send)
    out = hf.fetch_folder("appdata", send=net.send)
    assert (out["fetched"], out["errors"]) == (1, [])
    there = net.shares[B]["appdata"]
    assert _tree(there) == {"plex/Preferences.xml": "<prefs/>", "kiboto/data/users.db": "second NAS people"}
    with pytest.raises(ha.LinkError):  # asked for by name, it is refused too
        ha.call("file_piece", {"name": "appdata", "rel": "kiboto/data/keys.json", "offset": 0}, send=net.send)
    with pytest.raises(ha.LinkError):  # and never written here
        hf._inside(there, "kiboto/data/users.db")


def test_a_name_from_the_other_box_cannot_leave_the_folder_here_either(tmp_path):
    for rel in ("../x", "/abs", "a//b", "a/./b", f"{hf.REMOVED}/2026-01-01/x", "a\x00b", ""):
        with pytest.raises(ha.LinkError):
            hf._inside(str(tmp_path), rel)
    assert hf._inside(str(tmp_path), "a/b c/d.txt") == str(tmp_path / "a" / "b c" / "d.txt")


def test_a_full_second_nas_stops_the_fetch_and_keeps_what_it_has(net, monkeypatch):
    net.put(A, "Films", "a.txt", "one")
    net.put(A, "Films", "b.txt", "two")
    hf.fetch_folder("Films", send=net.send)
    net.put(A, "Films", "c.txt", "three")

    class Full:
        free = 10

    monkeypatch.setattr(hf.shutil, "disk_usage", lambda path: Full)
    out = hf.fetch_folder("Films", send=net.send)
    assert (out["why"], out["fetched"], out["removed"]) == ("full", 0, 0)
    assert sorted(_tree(net.shares[B]["Films"])) == ["a.txt", "b.txt"]
    assert sorted(hf._fetched_before("Films")) == ["a.txt", "b.txt"]  # still known as fetched for the next night


def test_the_other_box_going_away_midway_changes_nothing_that_was_recorded(net):
    net.put(A, "Films", "a.txt", "one")
    hf.fetch_folder("Films", send=net.send)
    net.put(A, "Films", "b.txt", "two")
    net.down = True
    with pytest.raises(ha.LinkError) as e:
        hf.fetch_folder("Films", send=net.send)
    assert e.value.key == "unreachable" and sorted(hf._fetched_before("Films")) == ["a.txt"]
    out = hf.fetch_all(send=net.send)
    assert out == {}  # nothing chosen yet
    net.down = False
    hf.choose(["Films"], send=net.send)
    net.down = True
    out = hf.fetch_all(send=net.send)
    assert out["Films"]["why"] == "unreachable" and hf.view()["folders_last"]["Films"]["why"] == "unreachable"


def test_choosing_takes_only_folders_the_first_nas_has(net):
    net.put(A, "Films", "a.txt")
    net.put(A, "Photos", "p.jpg")
    with pytest.raises(ha.LinkError) as e:
        hf.choose(["Films", "Nope"], send=net.send)
    assert e.value.key == "no_folder"
    with pytest.raises(ha.LinkError) as e:
        hf.choose([f"f{i}" for i in range(hf.MAX_FOLDERS + 1)], send=net.send)
    assert e.value.key == "too_many_folders"
    assert hf.choose(["Photos", "Films", "Films"], send=net.send) == ["Films", "Photos"]
    out = hf.fetch_all(send=net.send)
    assert sorted(out) == ["Films", "Photos"] and hf.view()["folders_last"]["Photos"]["fetched"] == 1
    assert hf.choose([], send=net.send) == [] and hf.view() == {
        "folders": [],
        "folders_last": {},
        "keep_removed_days": 30,
    }
    net.on(A)
    with pytest.raises(ha.LinkError) as e:
        hf.choose(["Films"], send=net.send)
    assert e.value.key == "not_second" and hf.fetch_all(send=net.send) == {}


def test_unpairing_forgets_the_choice_and_leaves_the_copies(net):
    net.put(A, "Films", "a.txt", "one")
    hf.choose(["Films"], send=net.send)
    hf.fetch_all(send=net.send)
    ha.unpair("ana", send=net.send)
    assert hf.chosen() == [] and hf._fetched_before("Films") == {}
    assert _tree(net.shares[B]["Films"]) == {"a.txt": "one"}  # the files themselves stay


def test_over_the_api_the_second_nas_chooses_its_folders(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(ha, "STATE_FILE", str(tmp_path / "ha.json"))
    monkeypatch.setattr(hf, "DIR", str(tmp_path / "ha"))
    monkeypatch.setattr(ha, "audit", lambda *a: None)
    res = client.get("/api/ha/folders", headers=auth_headers)
    assert res.status_code == 409 and res.json()["error"] == "ha_not_second"  # not paired, or the first NAS
    monkeypatch.setattr(ha, "role", lambda: "second")
    monkeypatch.setattr(hf, "available", lambda send=None: ["Films", "Photos"])
    started = []
    monkeypatch.setattr("backend.services.ha_state.fetch_soon", lambda: started.append(1) or True)
    seen = client.get("/api/ha/folders", headers=auth_headers).json()
    assert seen["available"] == ["Films", "Photos"] and seen["folders"] == [] and seen["keep_removed_days"] == 30
    saved = client.put("/api/ha/folders", json={"names": ["Photos", " Films "]}, headers=auth_headers)
    assert saved.status_code == 200 and saved.json()["folders"] == ["Films", "Photos"] and started == [1]
    bad = client.put("/api/ha/folders", json={"names": ["Nope"]}, headers=auth_headers)
    assert bad.status_code == 400 and bad.json()["error"] == "ha_no_folder"
    assert bad.json()["text"]["msg_key"] == "srv.ha_no_folder"

    def away(send=None):
        raise ha.LinkError("unreachable", "The other NAS did not answer.")

    monkeypatch.setattr(hf, "available", away)
    seen = client.get("/api/ha/folders", headers=auth_headers).json()
    assert seen["available"] is None and seen["error"] == "unreachable" and seen["folders"] == ["Films", "Photos"]


@pytest.mark.real_confirmations
def test_choosing_folders_asks_first_and_names_them(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(ha, "STATE_FILE", str(tmp_path / "ha.json"))
    monkeypatch.setattr(hf, "DIR", str(tmp_path / "ha"))
    assert client.put("/api/ha/folders", json={"names": ["Films", "Photos"]}, headers=auth_headers).status_code == 428
    made = client.post(
        "/api/confirmations", json={"action": "ha.folders", "target": "Films, Photos"}, headers=auth_headers
    )
    assert made.status_code == 200 and "Films, Photos" in made.json()["summary"]


def test_on_kiboto_os_what_is_fetched_goes_to_the_shared_folders_people(net, monkeypatch):
    """There Kiboto does not run as root: fetched files and the folders made for them stayed Kiboto's
    own user's, and the shared folder's people could not change them on this NAS."""
    from backend import owned, runtime

    net.put(A, "Films", "2019/summer/a.mkv", "a")
    handed = []
    monkeypatch.setattr(runtime, "without_root", lambda: True)
    monkeypatch.setattr(owned, "like_folder", lambda path: handed.append(path) or True)
    hf.choose(["Films"], send=net.send)
    assert hf.fetch_folder("Films", send=net.send)["fetched"] == 1
    there = net.shares[B]["Films"]
    assert [os.path.relpath(p, there) for p in handed] == ["2019", "2019/summer", "2019/summer/a.mkv"]
