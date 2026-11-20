"""High availability, the takeover (the owner's decisions of 19 Nov 2026: by a button; only the name
moves; people and settings are applied then; going back by hand). Two boxes are played by one
process, as in test_ha_state.py. The copy is a real encrypted settings backup of a made-up first
NAS, with files of its hardware in it that must not arrive."""

import base64
import copy
import io
import json
import os
import sqlite3
import time
import zipfile

import pytest

from backend import config, secret_box
from backend.services import backup_engine as be
from backend.services import box_restore, ha_bring, ha_folders, nas_name
from backend.services import ha_link as ha
from backend.services import ha_state as hs
from backend.services import ha_takeover as ht

A, B = "http://192.168.1.10:8082", "http://192.168.1.20:8082"
FIRST_KEY = "the-first-nas-secret-key"
SEED = "JBSWY3DPEHPK3PXP"


def first_nas_backup(folder) -> bytes:
    """A settings backup as the first NAS makes it: its people, and a good deal that is its own."""
    db = folder / "users.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT, mfa_secret TEXT)")
    conn.execute("CREATE TABLE sessions (id TEXT)")
    conn.execute("CREATE TABLE api_tokens (id TEXT)")
    key = secret_box._key(FIRST_KEY)
    nonce = b"\x01" * 12
    sealed = secret_box.PREFIX + base64.urlsafe_b64encode(
        nonce + secret_box.AESGCM(key).encrypt(nonce, SEED.encode(), secret_box._AAD)
    ).decode("ascii")
    conn.execute("INSERT INTO users VALUES ('u1', 'ana', ?)", (sealed,))
    conn.execute("INSERT INTO users VALUES ('u2', 'ben', '')")
    conn.commit()
    conn.close()

    def sealed_by_first(text):
        n = b"\x03" * 12
        return secret_box.PREFIX + base64.urlsafe_b64encode(
            n + secret_box.AESGCM(key).encrypt(n, text.encode(), secret_box._AAD)
        ).decode("ascii")

    job = {
        "kind": "data",
        "source_pool": "pool-of-the-first",
        "enabled": True,
        "last_status": "success",
        "schedule": "daily",
    }
    jobs = [
        {
            **job,
            "id": "j1",
            "source_subvolume": "photos",
            "destination_type": "remote",
            "remote_name": "cloud",
            "encryption_password": sealed_by_first("job-pass"),
        },
        {**job, "id": "j2", "source_subvolume": "taxes", "destination_type": "remote", "remote_name": "cloud"},
        {
            **job,
            "id": "j3",
            "kind": "config",
            "source_subvolume": "",
            "destination_type": "remote",
            "remote_name": "cloud",
        },
        {
            **job,
            "id": "j4",
            "source_subvolume": "photos",
            "destination_type": "local_snapshot",
            "encryption_password": "",
        },
        {**job, "id": "j5", "source_subvolume": "photos", "destination_type": "remote", "remote_name": "clash"},
    ]
    repo = {"keep": 7, "hour": 3, "initialized": True, "last_backup": 1763600000, "last_result": "ok"}
    repos = {
        "r1": {
            **repo,
            "id": "r1",
            "location": "rclone:cloud:restic",
            "paths": ["/mnt/first/photos", "/mnt/first/taxes"],
        },
        "r2": {**repo, "id": "r2", "location": "/mnt/first/usb/restic", "paths": ["/mnt/first/photos"]},
        "r3": {**repo, "id": "r3", "location": "rest:https://backup.example/r3", "paths": ["/mnt/first/taxes"]},
        "r4": {
            **repo,
            "id": "r4",
            "location": "rest:https://backup.example/r4",
            "paths": ["/mnt/first/photos/2019"],
            "rest_user": "u",
            "rest_password": sealed_by_first("rest-pass"),
        },
    }
    remotes = "[base]\ntype = b2\naccount = A1\n\n[cloud]\ntype = crypt\nremote = base:bucket\npassword = obscured\n\n[clash]\ntype = s3\n"
    files = {
        "backup_jobs.json": json.dumps(jobs).encode(),
        "offsite_repos.json": json.dumps({"repos": repos}).encode(),
        **{f"offsite_keys/{r}.key": f"key-of-{r}".encode() for r in repos},
        "rclone/rclone.conf": remotes.encode(),
        "users.db": db.read_bytes(),
        "secret.key": FIRST_KEY.encode(),
        "vapid.json": b'{"private": "p"}',
        "nas_name.json": json.dumps({"enabled": True, "name": "familynas", "previous": []}).encode(),
        "share_access.json": json.dumps(
            {
                "default_level": "none",
                "shares": {"photos": {"users": {"ana": "write"}}, "taxes": {"users": {"ana": "read"}}},
            }
        ).encode(),
        "network_config.json": b'{"address": "192.168.1.10"}',
        "ha.json": b'{"role": "first"}',
        "fan_state.json": b"{}",
        "samba/private/passdb.tdb": b"TDB people",
        "samba/smb.conf": b"[photos]\npath = /mnt/pool-of-the-first/photos\n",
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
        z.writestr(be.MANIFEST_NAME, json.dumps({"format": be.FORMAT_VERSION, "files": list(files)}))
    return out.getvalue()


class Net:
    def __init__(self, tmp_path, monkeypatch):
        self.dirs = {A: tmp_path / "first", B: tmp_path / "second"}
        for d in self.dirs.values():
            d.mkdir()
        self.patch, self.me, self.down = monkeypatch, A, set()
        (tmp_path / "made").mkdir()
        plain = first_nas_backup(tmp_path / "made")
        monkeypatch.setattr(hs, "make_archive", lambda passphrase: be.encrypt_backup(plain, passphrase))
        monkeypatch.setattr(ha, "audit", lambda *a: None)
        monkeypatch.setattr(ha, "_seen", {})
        monkeypatch.setattr(ha, "_last", {"at": 0.0, "ok": None, "error": ""})
        monkeypatch.setattr(hs, "_offers", {})
        monkeypatch.setattr(hs, "_state", {"fetching": False, "error": "", "ran": ""})
        monkeypatch.setattr(ht, "_asked", {"at": 0.0})
        self.named = []
        monkeypatch.setattr(nas_name, "ensure", lambda: self.named.append(nas_name.config()) or {"ok": True})
        monkeypatch.setattr(box_restore, "restart_to_apply", lambda delay=2.0: {"restarting": True})
        monkeypatch.setattr("backend.services.data_snapshot.take_snapshot", lambda *a, **k: "saved-first")
        monkeypatch.setattr(ha_folders, "chosen", lambda: ["photos", "films"])
        for box, name in ((A, "familynas"), (B, "spare")):
            (self.dirs[box] / "nas_name.json").write_text(json.dumps({"enabled": True, "name": name, "previous": []}))
        (self.dirs[B] / "share_access.json").write_text(
            json.dumps(
                {"default_level": "none", "shares": {"photos": {"users": {}}, "music": {"users": {"own": "write"}}}}
            )
        )
        self.on(A)

    def on(self, box):
        self.me = box
        self.patch.setattr(ha, "STATE_FILE", str(self.dirs[box] / "ha.json"))
        self.patch.setattr(hs, "DIR", str(self.dirs[box] / "ha"))
        self.patch.setattr(ha_folders, "DIR", str(self.dirs[box] / "ha"))
        self.patch.setattr(be, "DATA_DIR", str(self.dirs[box]))
        self.patch.setattr(nas_name, "STATE_FILE", str(self.dirs[box] / "nas_name.json"))

    def send(self, url, body):
        back, target = self.me, next(box for box in self.dirs if url.startswith(box))
        if target in self.down:
            raise ha.LinkError("unreachable", "The other NAS did not answer.")
        self.on(target)
        try:
            if url.endswith(ha.PAIR_PATH):
                said = ha.accept_pairing(body["box_id"], body["name"], body["address"], body["public"], body["proof"])
            else:
                said = ha.handle_call(copy.deepcopy(body))
        finally:
            self.on(back)
        return said


@pytest.fixture
def net(tmp_path, monkeypatch):
    made = Net(tmp_path, monkeypatch)
    made.on(A)
    code = ha.new_code("ana")["code"]
    made.on(B)
    ha.pair_with(A, code, B, "own", send=made.send)
    hs.fetch(send=made.send)
    return made


def staged_dir(net):
    return net.dirs[B] / be.STAGED_RESTORE_DIR


def test_the_second_nas_takes_the_people_the_access_and_the_name_and_nothing_else(net):
    net.down.add(A)  # the first NAS is gone
    said = ht.take_over("own", send=net.send)
    assert said["restarting"] is True and said["took_over"]["people"] == 2
    staged = staged_dir(net)
    kept = json.loads((staged / be.STAGED_MANIFEST).read_text())
    assert kept == ["users.db", "vapid.json", "samba/private/passdb.tdb", "share_access.json"]
    for its_own in (
        "secret.key",
        "network_config.json",
        "ha.json",
        "fan_state.json",
        "samba/smb.conf",
        "nas_name.json",
    ):
        assert not (staged / its_own).exists()  # the first NAS's key, address and hardware stay its own
    # two-factor: sealed with the first NAS's key in the copy, with this box's own after staging
    conn = sqlite3.connect(staged / "users.db")
    value = conn.execute("SELECT mfa_secret FROM users WHERE username = 'ana'").fetchone()[0]
    conn.close()
    assert secret_box.unseal(value) == SEED
    # who may open the folders kept in step comes from the first NAS; the others here stay as they are
    access = json.loads((staged / "share_access.json").read_text())["shares"]
    assert access["photos"] == {"users": {"ana": "write"}} and access["music"] == {"users": {"own": "write"}}
    assert "taxes" not in access  # a folder this box does not keep
    # the name moves, and the old one still answers
    assert nas_name.config()["name"] == "familynas" and nas_name.config()["previous"] == ["spare"]
    assert ha.role() == "took_over" and ht.view()["took_over"]["name"] == "familynas"
    # and at the next start the staged people are put in place
    assert sorted(be.apply_staged_restore(str(net.dirs[B]))) == sorted(kept)
    assert (net.dirs[B] / "samba" / "private" / "passdb.tdb").read_bytes() == b"TDB people"
    assert not (net.dirs[B] / "network_config.json").exists()


def test_a_box_that_took_over_fetches_nothing_more(net, monkeypatch):
    net.down.add(A)
    ht.take_over("own", send=net.send)
    started = []
    monkeypatch.setattr(hs, "fetch_soon", lambda: started.append(1) or True)
    assert hs.run_due(time.mktime((2026, 11, 21, 2, 30, 10, 0, 0, -1))) is False and started == []
    assert ha_folders.fetch_all(send=net.send) == {}
    with pytest.raises(ha.LinkError) as e:
        ht.take_over("own", send=net.send)  # nor does it take over twice
    assert e.value.key == "not_second"


def test_it_is_refused_while_the_first_nas_answers_unless_that_is_known(net):
    with pytest.raises(ha.LinkError) as e:
        ht.take_over("own", send=net.send)
    assert e.value.key == "first_answers" and not staged_dir(net).exists() and ha.role() == "second"
    ht.take_over("own", even_if_answering=True, send=net.send)
    assert ha.role() == "took_over"
    net.on(A)  # the first NAS was told, and is silent at once
    assert ht.stood_down() is not None and nas_name.config()["held"] is True and ha.role() == "first"
    assert nas_name.config()["enabled"] is True  # its setting is as it was


def test_taking_over_needs_a_pair_and_a_copy_that_can_be_read(net):
    net.on(A)
    with pytest.raises(ha.LinkError) as e:
        ht.take_over("ana", send=net.send)
    assert e.value.key == "not_second"
    net.on(B)
    net.down.add(A)
    with open(os.path.join(hs.DIR, hs.COPY), "r+b") as f:
        f.seek(40)
        f.write(b"\x00" * 16)  # the kept copy is damaged
    with pytest.raises(ha.LinkError) as e:
        ht.take_over("own", send=net.send)
    assert e.value.key == "bad_copy" and not staged_dir(net).exists() and ha.role() == "second"
    hs.forget()
    with pytest.raises(ha.LinkError) as e:
        ht.take_over("own", send=net.send)
    assert e.value.key == "no_copy"


def test_a_first_nas_that_comes_back_holds_its_name_until_it_is_taken_back(net):
    net.down.add(A)
    ht.take_over("own", send=net.send)
    net.down.clear()  # the first NAS is started again
    net.on(A)
    assert ht.stood_down() is None
    ha.check(send=net.send)  # it asks before it answers to its name
    assert ht.stood_down() is not None and nas_name.config()["held"] is True
    assert ht.view() == {"took_over": None, "stood_down": {"at": ht.stood_down()["at"]}}
    first_at = ht.stood_down()["at"]
    ha.check(send=net.send)
    assert ht.stood_down()["at"] == first_at  # asked again: nothing new
    # taking the name back: the second NAS stops, and is called what it was called
    ht.take_back("ana", send=net.send)
    assert ht.stood_down() is None and nas_name.config()["held"] is False
    net.on(B)
    assert ha.role() == "second" and ht.took_over() is None
    assert nas_name.config()["name"] == "spare" and "familynas" not in nas_name.answering_names(nas_name.config())


def test_the_name_is_taken_back_from_a_second_nas_that_is_off_only_when_that_is_known(net):
    net.down.add(A)
    ht.take_over("own", send=net.send)
    net.down.clear()
    net.on(A)
    ha.check(send=net.send)
    net.down.add(B)
    with pytest.raises(ha.LinkError) as e:
        ht.take_back("ana", send=net.send)
    assert e.value.key == "second_unreachable" and ht.stood_down() is not None
    ht.take_back("ana", even_if_unreachable=True, send=net.send)
    assert ht.stood_down() is None and nas_name.config()["held"] is False
    with pytest.raises(ha.LinkError) as e:
        ht.take_back("ana", send=net.send)
    assert e.value.key == "not_held"


def test_a_second_nas_that_holds_nothing_does_not_stop_the_name_from_coming_back(net):
    net.on(A)
    ht._hold("a test")  # the first NAS holds its name, the second one never took over
    ht.take_back("ana", send=net.send)  # it refuses the release, which is fine: it holds nothing
    assert ht.stood_down() is None
    net.on(A)
    with pytest.raises(ha.LinkError) as e:
        ha.call("stand_down", send=net.send)  # and a second NAS does not stand down for a first one
    assert e.value.key == "refused"


def test_unpairing_ends_all_of_it(net):
    net.down.add(A)
    ht.take_over("own", send=net.send)
    net.down.clear()
    net.on(A)
    ha.check(send=net.send)
    ha.unpair("ana", send=net.send)
    assert ht.stood_down() is None and nas_name.config()["held"] is False
    net.on(B)
    assert ht.took_over() is None and ha.role() == ""
    assert nas_name.config()["name"] == "familynas"  # each keeps the name it has at that moment


def test_a_first_nas_asks_its_second_one_at_start_and_now_and_then(net, monkeypatch):
    class Now:
        def __init__(self, target=None, name="", daemon=False):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(ht.threading, "Thread", Now)
    asked = []
    monkeypatch.setattr(ha, "check", lambda: asked.append(ha.role()))
    net.on(B)
    ht.name_at_start()
    assert asked == [] and len(net.named) == 1  # a second NAS just starts its name service
    assert ht.watch(1000.0) is False
    net.on(A)
    ht.name_at_start()
    assert asked == ["first"] and len(net.named) == 2
    now = time.time()
    assert ht.watch(now + 60) is False  # it asked at start
    assert ht.watch(now + ht.ASK_EVERY + 1) is True and ht.watch(now + ht.ASK_EVERY + 60) is False
    assert asked == ["first", "first"]
    monkeypatch.setattr(nas_name, "ensure", lambda: (_ for _ in ()).throw(OSError("no docker")))
    ht.name_at_start()  # a failure is logged, not raised


def test_a_new_secret_key_keeps_the_pair(net, tmp_path, monkeypatch):
    """key_rotation seals again what the old key sealed; the link's key and the copy's were left out."""
    old = str(config.SECRET_KEY)
    key_file = tmp_path / "secret.key"
    monkeypatch.setattr(config, "SECRET_KEY_FILE", str(key_file))
    (tmp_path / "secret.key.previous").write_text(old)
    monkeypatch.setattr(config, "SECRET_KEY", "a-new-key-after-rotation")
    assert ha.reseal() == 1 and hs.reseal() == 1
    net.on(A)
    assert ha.reseal() == 1 and hs.reseal() == 0  # the first NAS keeps no copy
    net.on(B)
    os.remove(tmp_path / "secret.key.previous")
    assert len(ha._key_of(ha.peer())) == 32 and len(hs.passphrase()) >= 40
    assert ha.call("hello", send=net.send)["role"] == "first"  # the link still works
    hs.forget()
    assert hs.reseal() == 0


def test_a_secret_of_the_other_nas_opens_only_with_its_key():
    monkey = secret_box._key(FIRST_KEY)
    nonce = b"\x02" * 12
    sealed = secret_box.PREFIX + base64.urlsafe_b64encode(
        nonce + secret_box.AESGCM(monkey).encrypt(nonce, b"seed", secret_box._AAD)
    ).decode("ascii")
    assert secret_box.unseal_with(sealed, FIRST_KEY) == "seed"
    assert secret_box.unseal_with("plain", FIRST_KEY) == "plain" and secret_box.unseal_with("", FIRST_KEY) == ""
    for wrong in ("another-key", ""):
        with pytest.raises(secret_box.SecretBoxError):
            secret_box.unseal_with(sealed, wrong)


def test_a_copy_without_people_is_not_used(net, monkeypatch):
    net.down.add(A)
    monkeypatch.setattr(ht, "PEOPLE_FILES", ("nobody.db",))
    with pytest.raises(ha.LinkError) as e:
        ht.take_over("own", send=net.send)
    assert e.value.key == "bad_copy" and not staged_dir(net).exists()


def test_over_the_api(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(ha, "STATE_FILE", str(tmp_path / "ha.json"))
    monkeypatch.setattr(hs, "DIR", str(tmp_path / "ha"))
    status = client.get("/api/ha", headers=auth_headers).json()
    assert status["took_over"] is None and status["stood_down"] is None
    res = client.post("/api/ha/takeover", json={}, headers=auth_headers)
    assert res.status_code == 409 and res.json()["error"] == "ha_not_second"
    res = client.post("/api/ha/take-back", json={}, headers=auth_headers)
    assert res.status_code == 409 and res.json()["error"] == "ha_not_held"
    assert res.json()["text"]["msg_key"] == "srv.ha_not_held"
    asked = []
    monkeypatch.setattr(
        ht,
        "take_over",
        lambda actor, anyway, bring: asked.append((anyway, bring)) or {"restarting": True, "took_over": {}},
    )
    said = client.post("/api/ha/takeover", json={"even_if_answering": True, "bring": ["backups"]}, headers=auth_headers)
    assert said.status_code == 200 and said.json()["restarting"] is True and asked == [(True, ("backups",))]
    assert (
        client.post("/api/ha/takeover", json={"bring": ["the kitchen sink"]}, headers=auth_headers).status_code == 422
    )
    monkeypatch.setattr(ht, "take_back", lambda actor, anyway: asked.append(("back", anyway)))
    assert client.post("/api/ha/take-back", json={}, headers=auth_headers).status_code == 200
    assert asked[-1] == ("back", False)

    def bad(actor, anyway, bring):
        raise ha.LinkError("bad_copy", "The kept copy could not be used: damaged")

    monkeypatch.setattr(ht, "take_over", bad)
    assert client.post("/api/ha/takeover", json={}, headers=auth_headers).status_code == 400


HERE = {
    "shares": {"photos": "/mnt/tank/photos", "music": "/mnt/tank/music"},
    "pools": [("/mnt", "wrong"), ("/mnt/tank", "tank")],
    "first_paths": {"photos": "/mnt/first/photos", "taxes": "/mnt/first/taxes"},
}


def test_the_backups_come_along_switched_off_when_asked(net, monkeypatch):
    """The owner, 20 Nov 2026: "give the option to the user"."""
    assert hs.info()["holds"] == {"backup_jobs": 4, "offsite": 4}  # what the card can say before
    monkeypatch.setattr(ha_bring, "here", lambda: HERE)
    (net.dirs[B] / "backup_jobs.json").write_text(json.dumps([{"id": "own1", "enabled": True}]))
    (net.dirs[B] / "rclone").mkdir()
    (net.dirs[B] / "rclone" / "rclone.conf").write_text("[clash]\ntype = sftp\n")
    net.down.add(A)
    said = ht.take_over("own", bring=("backups", "the kitchen sink"), send=net.send)
    assert said["took_over"]["brought"] == {"jobs": 2, "jobs_left": 2, "offsite": 2, "offsite_left": 2}
    assert ht.view()["took_over"]["brought"]["jobs"] == 2
    staged = staged_dir(net)
    kept = json.loads((staged / be.STAGED_MANIFEST).read_text())
    assert kept[4:] == [
        "backup_jobs.json",
        "offsite_repos.json",
        "offsite_keys/r1.key",
        "offsite_keys/r4.key",
        "rclone/rclone.conf",
    ]
    jobs = {j["id"]: j for j in json.loads((staged / "backup_jobs.json").read_text())}
    assert list(jobs) == ["own1", "j1", "j4"] and jobs["own1"] == {"id": "own1", "enabled": True}
    # switched off, pointed at this box's pool, its password sealed with this box's key
    assert (
        jobs["j1"]["enabled"] is False and jobs["j1"]["source_pool"] == "tank" and jobs["j1"]["last_status"] == "idle"
    )
    assert (
        secret_box.unseal(jobs["j1"]["encryption_password"]) == "job-pass" and jobs["j4"]["encryption_password"] == ""
    )
    repos = json.loads((staged / "offsite_repos.json").read_text())["repos"]
    assert sorted(repos) == ["r1", "r4"]  # r2 is on a drive of the first NAS, r3 backs up a folder not kept here
    assert (
        repos["r1"]["paths"] == ["/mnt/tank/photos"]
        and repos["r1"]["hour"] is None
        and repos["r1"]["last_backup"] is None
    )
    assert (
        repos["r4"]["paths"] == ["/mnt/tank/photos/2019"]
        and secret_box.unseal(repos["r4"]["rest_password"]) == "rest-pass"
    )
    assert (staged / "offsite_keys" / "r1.key").read_text() == "key-of-r1"
    assert oct((staged / "offsite_keys" / "r1.key").stat().st_mode & 0o777) == "0o600"
    assert not (staged / "offsite_keys" / "r2.key").exists()
    conf = (staged / "rclone" / "rclone.conf").read_text()
    # the sign-in a backup needs comes with the one it builds on; this box's own "clash" is not replaced
    assert "[cloud]" in conf and "[base]" in conf and "account = A1" in conf
    assert conf.count("[clash]") == 1 and "type = sftp" in conf and "type = s3" not in conf
    assert sorted(be.apply_staged_restore(str(net.dirs[B]))) == sorted(kept)


def test_nothing_of_the_backups_comes_unless_asked(net, monkeypatch):
    monkeypatch.setattr(ha_bring, "here", lambda: HERE)
    net.down.add(A)
    said = ht.take_over("own", send=net.send)
    assert said["took_over"]["brought"] == {}
    staged = staged_dir(net)
    for name in ("backup_jobs.json", "offsite_repos.json", "offsite_keys", "rclone"):
        assert not (staged / name).exists() or not any((staged / name).iterdir())


def test_a_box_that_cannot_place_a_backup_leaves_it_behind(net, monkeypatch):
    """No pool known for the folder, no word of where the first NAS has its folders, sign-ins that cannot be read."""
    monkeypatch.setattr(ha_bring, "here", lambda: {"shares": HERE["shares"], "pools": [], "first_paths": {}})
    net.down.add(A)
    said = ht.take_over("own", bring=("backups",), send=net.send)
    assert said["took_over"]["brought"] == {"jobs": 0, "jobs_left": 4, "offsite": 0, "offsite_left": 4}
    assert json.loads((staged_dir(net) / be.STAGED_MANIFEST).read_text())[4:] == []
    assert ha_bring._pool_of("/mnt/tank/photos", HERE["pools"]) == "tank" and ha_bring._pool_of("", HERE["pools"]) == ""
    assert ha_bring._mapped("/mnt/first/photos", [("/mnt/first/photos", "/mnt/tank/photos")]) == "/mnt/tank/photos"
    assert ha_bring._mapped("/mnt/first/photos-old/x", [("/mnt/first/photos", "/mnt/tank/photos")]) == ""
    assert ha_bring.counts({"backup_jobs.json"}, lambda name: b"not json") == {}
    assert ha_bring.counts(set(), lambda name: b"") == {"backup_jobs": 0, "offsite": 0}
    assert ha_bring._parse("no section header\nx = 1\n").sections() == []
    plan, counted = ha_bring.plan_backups(
        {
            "jobs": [
                {"id": "j", "source_subvolume": "photos", "remote_name": "cloud", "encryption_password": "enc1:AAAA"}
            ],
            "repos": {},
            "remotes": "[cloud]\ntype = s3\n",
            "keys": {},
        },
        {"jobs": [], "repos": {}, "remotes": "", "keys": {}},
        "wrong-key",
        ["photos"],
        HERE,
    )
    assert counted["jobs_left"] == 1 and plan["jobs"] == []  # a password that cannot be opened


def test_the_second_nas_learns_where_the_first_one_has_its_folders(net, monkeypatch):
    monkeypatch.setattr(ha_folders, "shares", lambda: {"photos": "/mnt/first/photos", "odd": "relative"})
    assert ha_folders.first_paths() == {}
    ha_folders.learn_paths(send=net.send)
    assert ha_folders.first_paths() == {"photos": "/mnt/first/photos"}
    net.down.add(A)
    ha_folders.learn_paths(send=net.send)  # not reached: what is known stays
    assert ha_folders.first_paths() == {"photos": "/mnt/first/photos"} and ha_folders.chosen() == ["photos", "films"]


def test_this_boxes_folders_and_pools(monkeypatch):
    from types import SimpleNamespace

    from backend.hardware import pal_storage

    pools = [SimpleNamespace(id="tank", mountpoint="/mnt/tank/"), SimpleNamespace(id="none", mountpoint=None)]
    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: SimpleNamespace(list_pools=lambda: pools))
    monkeypatch.setattr(ha_folders, "shares", lambda: {"photos": "/mnt/tank/photos"})
    monkeypatch.setattr(ha_folders, "first_paths", lambda: {"photos": "/mnt/first/photos"})
    assert ha_bring.here() == {
        "shares": {"photos": "/mnt/tank/photos"},
        "pools": [("/mnt/tank", "tank")],
        "first_paths": {"photos": "/mnt/first/photos"},
    }

    def broken():
        raise OSError("no storage")

    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: SimpleNamespace(list_pools=broken))
    assert ha_bring.here()["pools"] == []
