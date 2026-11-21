"""A copy of the settings on every pool of a machine set up for Kiboto."""

import io
import json
import os
import stat
import zipfile

import pytest

from backend import machine_key, runtime
from backend.hardware import power_state
from backend.services import backup_engine, pool_copy

KEY = "k" * 64


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A managed host with three "pools" (folders that count as mounted) and a data key."""
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / machine_key.WRAPPED).write_text('{"v": 1, "wrapped": true}')
    (keys / machine_key.CRED).write_text("sealed")
    monkeypatch.setattr(machine_key, "DIR", str(keys))
    monkeypatch.setattr(machine_key, "key_text", lambda do=None: KEY)
    rows = []
    for name in ("tank", "media", "docs"):
        (tmp_path / "pools" / name).mkdir(parents=True)
        rows.append({"name": name, "mountpoint": str(tmp_path / "pools" / name), "members": [f"/dev/{name}"]})
    rows.append({"name": "away", "mountpoint": str(tmp_path / "pools" / "away"), "members": []})  # not mounted
    rows.append({"name": "out", "mountpoint": str(tmp_path / "pools" / "tank"), "members": [], "ejected": True})
    from backend.hardware.pal import pool_registry

    monkeypatch.setattr(pool_registry, "load", lambda: rows)
    monkeypatch.setattr(os.path, "ismount", lambda p: os.path.isdir(p) and "pools" in p)
    made = type("Box", (), {"sleeping": set(), "archives": 0, "root": tmp_path / "pools"})()
    monkeypatch.setattr(pool_copy, "asleep", lambda row: row["name"] in made.sleeping)

    def archive(data_key):
        made.archives += 1
        return (
            backup_engine.ENCRYPTED_MAGIC + f"settings {made.archives} under {pool_copy.passphrase(data_key)}".encode()
        )

    monkeypatch.setattr(pool_copy, "_archive", archive)
    monkeypatch.setattr(pool_copy, "_named", lambda: "attic")
    return made


def files(box, pool):
    out = []
    for root, _dirs, names in os.walk(box.root / pool / ".kiboto"):
        out += [os.path.relpath(os.path.join(root, n), box.root / pool / ".kiboto") for n in names]
    return sorted(out)


def test_a_guest_keeps_no_copy_on_its_hosts_drives(tmp_path):
    assert pool_copy.copy_if_due() == {}
    assert pool_copy.status() == {"managed": False}


def test_every_mounted_pool_gets_the_copy_the_wrapped_key_and_a_note(box):
    assert pool_copy.copy_if_due(now=1000.0) == {"tank": "copied", "media": "copied", "docs": "copied"}
    assert box.archives == 1  # one archive for the round
    for pool in ("tank", "media", "docs"):
        assert files(box, pool) == ["about.json", "data-key.recovery", "settings.kbak"]
        folder = box.root / pool / ".kiboto"
        assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700
        assert all(stat.S_IMODE(os.stat(folder / n).st_mode) == 0o600 for n in files(box, pool))
        about = json.loads((folder / "about.json").read_text())
        assert about == {
            "format": 1,
            "install": pool_copy.install_id(),
            "name": "attic",
            "version": about["version"],
            "at": 1000.0,
            "pool": pool,
        }
        assert (folder / "data-key.recovery").read_text() == '{"v": 1, "wrapped": true}'
        assert KEY.encode() not in (folder / "settings.kbak").read_bytes()
    assert not os.path.exists(box.root / "away")  # a pool that is away is not written into its empty folder


def test_once_a_day_and_the_copy_before_is_kept(box):
    pool_copy.copy_if_due(now=1000.0)
    assert pool_copy.copy_if_due(now=1000.0 + 3600) == {"tank": "waiting", "media": "waiting", "docs": "waiting"}
    assert box.archives == 1
    assert pool_copy.copy_if_due(now=1000.0 + pool_copy.EVERY + 1)["tank"] == "copied"
    assert files(box, "tank") == ["about.json", "data-key.recovery", "settings.kbak", "settings.kbak.1"]
    assert b"settings 1 " in (box.root / "tank" / ".kiboto" / "settings.kbak.1").read_bytes()
    assert b"settings 2 " in (box.root / "tank" / ".kiboto" / "settings.kbak").read_bytes()


def test_a_sleeping_pool_is_left_asleep_and_gets_its_copy_when_it_is_awake(box):
    box.sleeping = {"media"}
    assert pool_copy.copy_if_due(now=1000.0) == {"tank": "copied", "media": "asleep", "docs": "copied"}
    assert not os.path.exists(box.root / "media" / ".kiboto")
    assert pool_copy.copy_if_due(now=1000.0, force=True)["media"] == "asleep"  # not even when asked
    box.sleeping = set()
    assert pool_copy.copy_if_due(now=2000.0) == {"tank": "waiting", "media": "copied", "docs": "waiting"}
    assert [p["at"] for p in pool_copy.status()["pools"]] == [1000.0, 2000.0, 1000.0]


def test_all_pools_asleep_makes_no_archive_at_all(box):
    box.sleeping = {"tank", "media", "docs"}
    assert set(pool_copy.copy_if_due(now=1000.0).values()) == {"asleep"}
    assert box.archives == 0


def test_another_installs_copy_is_set_aside_not_written_over(box):
    theirs = box.root / "docs" / ".kiboto"
    theirs.mkdir()
    (theirs / "about.json").write_text(json.dumps({"install": "feedfacefeedface", "name": "old-attic"}))
    (theirs / "settings.kbak").write_bytes(b"their settings")
    (theirs / "data-key.recovery").write_text("their wrapped key")
    pool_copy.copy_if_due(now=1000.0)
    assert files(box, "docs") == [
        "about.json",
        "data-key.recovery",
        "earlier/feedfacefeedface/about.json",
        "earlier/feedfacefeedface/data-key.recovery",
        "earlier/feedfacefeedface/settings.kbak",
        "settings.kbak",
    ]
    assert (theirs / "earlier" / "feedfacefeedface" / "settings.kbak").read_bytes() == b"their settings"
    assert json.loads((theirs / "about.json").read_text())["name"] == "attic"
    pool_copy.copy_if_due(now=1000.0, force=True)  # its own copy is replaced in place, with the one before kept
    assert "settings.kbak.1" in files(box, "docs") and "earlier/feedfacefeedface/settings.kbak" in files(box, "docs")


def test_an_id_in_a_strangers_note_cannot_name_a_folder_outside(box):
    theirs = box.root / "tank" / ".kiboto"
    theirs.mkdir()
    (theirs / "about.json").write_text(json.dumps({"install": "../../../etc/x"}))
    (theirs / "settings.kbak").write_bytes(b"x")
    pool_copy.copy_if_due(now=1000.0)
    assert "earlier/etcx/settings.kbak" in files(box, "tank")
    (theirs / "about.json").write_text(json.dumps({"install": "///"}))
    pool_copy.copy_if_due(now=1000.0, force=True)
    assert "earlier/unknown/settings.kbak" in files(box, "tank")


def test_a_pool_that_cannot_be_written_says_so_and_the_others_still_get_theirs(box, monkeypatch):
    real = pool_copy.write_one

    def write(row, *rest):
        if row["name"] == "media":
            raise OSError("No space left on device")
        real(row, *rest)

    monkeypatch.setattr(pool_copy, "write_one", write)
    assert pool_copy.copy_if_due(now=1000.0) == {"tank": "copied", "media": "No space left on device", "docs": "copied"}
    assert pool_copy.status()["pools"][1] == {"name": "media", "at": 0.0, "error": "No space left on device"}


def test_a_machine_that_cannot_open_its_key_writes_nothing(box, monkeypatch):
    def locked(do=None):
        raise machine_key.MachineKeyError(machine_key.LOCKED)

    monkeypatch.setattr(machine_key, "key_text", locked)
    out = pool_copy.copy_if_due(now=1000.0)
    assert all("could not open its data key" in said for said in out.values())
    assert not os.path.exists(box.root / "tank" / ".kiboto" / "settings.kbak")


def test_the_real_archive_is_encrypted_under_the_data_key_and_holds_the_pool_record(box, monkeypatch, tmp_path):
    monkeypatch.undo()  # the real archive this time; only the key and the slow KDF are stand-ins
    monkeypatch.setattr(backup_engine, "_derive_key", lambda passphrase, salt: (passphrase.encode() + salt)[:32])
    blob = pool_copy._archive(KEY)
    assert blob.startswith(backup_engine.ENCRYPTED_MAGIC)
    with zipfile.ZipFile(io.BytesIO(backup_engine.decrypt_backup(blob, pool_copy.passphrase(KEY)))) as z:
        manifest = json.loads(z.read(backup_engine.MANIFEST_NAME))
    assert manifest["encrypted"] is True and manifest["keys_included"] is True
    with pytest.raises(Exception, match="Wrong passphrase"):
        backup_engine.decrypt_backup(blob, pool_copy.passphrase("another key"))


def test_a_member_is_asked_as_the_whole_disk_and_a_virtual_disk_never_sleeps(monkeypatch, tmp_path):
    assert pool_copy._disk_of("/dev/nonexistent-sdq") == "nonexistent-sdq"
    asked = []
    from backend.hardware import disks

    monkeypatch.setattr(disks, "is_drive_asleep", lambda dev: asked.append(dev) or dev == "sdb")
    assert pool_copy.asleep({"members": ["/dev/sda", "/dev/sdb"]}) is True and asked == ["sda", "sdb"]
    assert pool_copy.asleep({"members": []}) is False
    for name in ("vda", "vdb", "xvda", "nvme0n1", "loop3"):
        assert power_state.probe(name) == power_state.ACTIVE, name  # no command is run for these


# --- the routes -----------------------------------------------------------------------------------
def test_the_page_reads_the_state_and_asks_for_a_copy_now(box, client, auth_headers):
    st = client.get("/api/system/settings-copy", headers=auth_headers).json()
    assert st["managed"] is True and [p["name"] for p in st["pools"]] == ["tank", "media", "docs"]
    assert all(p["at"] == 0 for p in st["pools"])
    box.sleeping = {"docs"}
    r = client.post("/api/system/settings-copy/now", headers=auth_headers)
    assert r.status_code == 200 and r.json()["done"] == {"tank": "copied", "media": "copied", "docs": "asleep"}
    assert [bool(p["at"]) for p in r.json()["pools"]] == [True, True, False]
    client.cookies.clear()
    assert client.get("/api/system/settings-copy").status_code == 401


def test_a_guest_has_no_copy_to_ask_for(client, auth_headers):
    assert client.get("/api/system/settings-copy", headers=auth_headers).json() == {"managed": False}
    assert client.post("/api/system/settings-copy/now", headers=auth_headers).status_code == 404
