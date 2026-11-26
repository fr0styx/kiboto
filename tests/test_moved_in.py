"""Settings moved from Kiboto Companion to Kiboto OS: shares are pointed at the pool that holds them."""

import os
from types import SimpleNamespace

from pydantic import BaseModel

from backend import runtime
from backend.services import backup_engine, moved_in


class Share(BaseModel):
    name: str
    path: str


class Engine:
    def __init__(self, items):
        self.items = {i.name: i for i in items}
        self.saved = []

    def list_shares(self):
        return list(self.items.values())

    list_exports = list_shares

    def add_or_update_share(self, item):
        self.items[item.name] = item
        self.saved.append(item.path)

    add_or_update_export = add_or_update_share


def _storage(tmp_path):
    root = tmp_path / "storage"
    for p in ("tank/photos", "tank/shares", "media/films", "media/both", "tank/both"):
        (root / p).mkdir(parents=True)
    (root / "here").mkdir()
    return root


def test_a_share_is_pointed_at_the_one_pool_that_holds_its_folder(tmp_path):
    root = _storage(tmp_path)
    pools = ["media", "tank"]
    r = str(root)
    assert moved_in.place(f"{r}/photos", r, pools) == f"{r}/tank/photos"
    assert moved_in.place(f"{r}/films", r, pools) == f"{r}/media/films"
    assert moved_in.place(f"{r}/both", r, pools) == ""  # on two pools: which one is not guessed
    assert moved_in.place(f"{r}/nowhere", r, pools) == ""
    assert moved_in.place(f"{r}/here", r, pools) == ""  # there: left alone
    assert moved_in.place(f"{r}/tank/gone", r, pools) == ""  # already on a pool
    assert moved_in.place(str(tmp_path / "elsewhere"), r, pools) == ""
    (root / "tank" / "linked").symlink_to(root / "tank" / "photos")
    assert moved_in.place(f"{r}/linked", r, pools) == ""  # never through a link


def test_fit_moves_samba_and_nfs_and_is_done_when_all_are_found(tmp_path):
    root = _storage(tmp_path)
    r = str(root)
    samba = Engine([Share(name="photos", path=f"{r}/photos"), Share(name="storage", path=f"{r}/shares")])
    nfs = Engine([Share(name="films", path=f"{r}/films")])
    (tmp_path / moved_in.FLAG).write_text("1")
    changed = moved_in.fit(str(tmp_path), r, ["media", "tank"], samba, nfs)
    assert sorted(changed) == sorted(
        [(f"{r}/photos", f"{r}/tank/photos"), (f"{r}/shares", f"{r}/tank/shares"), (f"{r}/films", f"{r}/media/films")]
    )
    assert samba.items["photos"].path == f"{r}/tank/photos" and nfs.items["films"].path == f"{r}/media/films"
    assert not moved_in.pending(str(tmp_path))


def test_a_share_on_no_pool_yet_waits_for_the_next_import(tmp_path, monkeypatch):
    root = _storage(tmp_path)
    r = str(root)
    samba = Engine([Share(name="later", path=f"{r}/later")])
    (tmp_path / moved_in.FLAG).write_text("1")
    assert moved_in.fit(str(tmp_path), r, ["media", "tank"], samba, Engine([])) == []
    assert moved_in.pending(str(tmp_path)) and samba.saved == []
    (root / "media" / "later").mkdir()  # the pool that holds it is imported
    assert moved_in.fit(str(tmp_path), r, ["media", "tank"], samba, Engine([])) == [(f"{r}/later", f"{r}/media/later")]
    assert not moved_in.pending(str(tmp_path))
    calls = []
    monkeypatch.setattr(moved_in, "fit", lambda d="": calls.append(d) or [])
    assert moved_in.fit_if_pending(str(tmp_path)) == [] and calls == []  # nothing waits: nothing done


def test_fit_if_pending_never_stops_the_start(tmp_path, monkeypatch):
    (tmp_path / moved_in.FLAG).write_text("1")

    def broken(d=""):
        raise RuntimeError("samba is not there")

    monkeypatch.setattr(moved_in, "fit", broken)
    assert moved_in.fit_if_pending(str(tmp_path)) == [] and moved_in.pending(str(tmp_path))


def test_only_kiboto_os_marks_a_restore_for_fitting(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "managed_host", lambda: False)
    assert moved_in.mark(str(tmp_path)) is False and not moved_in.pending(str(tmp_path))
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    assert moved_in.mark(str(tmp_path)) is True and moved_in.pending(str(tmp_path))


def test_a_restore_put_in_place_marks_the_shares_for_fitting(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    staged = tmp_path / backup_engine.STAGED_RESTORE_DIR
    staged.mkdir()
    (staged / "client_preferences.json").write_text("{}")
    (staged / backup_engine.STAGED_MANIFEST).write_text('["client_preferences.json"]')
    assert backup_engine.apply_staged_restore(str(tmp_path)) == ["client_preferences.json"]
    assert moved_in.pending(str(tmp_path))


def test_pools_are_the_mounted_folders_of_the_storage_folder(tmp_path, monkeypatch):
    root = _storage(tmp_path)
    monkeypatch.setattr(os.path, "ismount", lambda p: os.path.basename(p) in ("tank", "media"))
    assert moved_in._pools(str(root)) == ["media", "tank"]
    assert moved_in._pools(str(tmp_path / "none")) == []
    assert SimpleNamespace  # noqa: B018


class Samba:
    def __init__(self, ok=True):
        self.ok, self.set = ok, []

    def sync_samba_user(self, username, password):
        if self.ok == "broken":
            raise RuntimeError("smbpasswd failed")
        self.set.append(username)
        return self.ok


def test_after_a_move_each_person_gets_their_share_password_at_their_first_sign_in(tmp_path, monkeypatch):
    samba = Samba()
    assert moved_in.smb_at_sign_in("ann", "pw", str(tmp_path), samba) is False and samba.set == []  # no move
    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    moved_in.mark(str(tmp_path))
    assert moved_in.smb_at_sign_in("ann", "pw", str(tmp_path), samba) is True
    assert moved_in.smb_at_sign_in("ann", "pw", str(tmp_path), samba) is False  # once
    assert moved_in.smb_at_sign_in("bob", "pw", str(tmp_path), Samba(ok=False)) is False
    assert moved_in.smb_at_sign_in("bob", "pw", str(tmp_path), Samba(ok="broken")) is False
    assert moved_in.smb_at_sign_in("bob", "pw", str(tmp_path), samba) is True
    assert samba.set == ["ann", "bob"]
