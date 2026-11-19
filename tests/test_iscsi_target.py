"""Disks for other computers over iSCSI (owner's decision, 19 Nov 2026): off by default, every disk
behind a user name and a password, its file never removed by accident. The file the service reads
was tried against the real tgtd and a real initiator in a throwaway container; here it is read."""

import os

import pytest

from backend.services import iscsi_target as it

GIB = 1024**3


@pytest.fixture(autouse=True)
def box(tmp_path, monkeypatch):
    monkeypatch.setattr(it, "STATE_FILE", str(tmp_path / "data" / "iscsi.json"))
    monkeypatch.setattr(it, "CONF_DIR", str(tmp_path / "data" / "iscsi"))
    monkeypatch.setattr(it, "DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    share = tmp_path / "pool" / "My Files"
    share.mkdir(parents=True)
    monkeypatch.setattr(it, "ALLOWED_BROWSE_ROOTS", [str(tmp_path / "pool")])
    monkeypatch.setattr(it, "node", lambda: "nas")
    calls = []

    def docker(method, path, body=None, headers=None):
        calls.append((method, path, body, headers))
        if method == "GET" and path.endswith("/kiboto-iscsi/json"):
            return (200, box_state["container"]) if box_state["container"] else (404, None)
        if method == "GET":
            return 200, ME
        return 201 if "create" in path else 204, {}

    box_state = {"container": None, "calls": calls, "share": share, "tmp": tmp_path}
    monkeypatch.setattr(it, "_docker", docker)
    yield box_state


def _disk(**over):
    return {"name": "vm-disk", "size_gb": 1, "folder": "", "user": "ana", "secret": "secretsecret12", **over}


ME = {
    "Config": {"Image": "ghcr.io/example/kiboto:sha-abc"},
    "Mounts": [
        {"Source": "/mnt/user", "Destination": "/mnt/user"},
        {"Source": "/host/appdata/kiboto", "Destination": "/data"},
        {"Source": "/host/appdata/kiboto/deep", "Destination": "/data/deep"},
    ],
}


def test_off_until_turned_on_and_a_disk_is_a_sparse_file(box):
    assert it.enabled() is False and it.disks() == []
    made = it.save(_disk(folder=str(box["share"])))
    path = it.file_of(made)
    assert path == str(box["share"] / "vm-disk.iscsi.img") and os.path.getsize(path) == GIB
    assert os.stat(path).st_blocks == 0  # no space until the other computer writes
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert made["secret"] != "secretsecret12" and it.unseal(made["secret"]) == "secretsecret12"
    shown = it.public(made)
    assert "secret" not in shown and shown["iqn"] == "iqn.2026-11.net.kiboto:nas:vm-disk"
    assert shown["file_there"] is True and shown["used_bytes"] == 0 and shown["user"] == "ana"
    assert it.set_enabled(True) is True and it.enabled() is True and len(it.disks()) == 1


def test_what_a_disk_may_be(box):
    folder = str(box["share"])
    for change, key in [
        ({"name": "Has Space"}, "bad_name"),
        ({"name": "-starts-with-hyphen"}, "bad_name"),
        ({"name": "x" * 32}, "bad_name"),
        ({"size_gb": 0}, "bad_size"),
        ({"size_gb": it.MAX_GB + 1}, "bad_size"),
        ({"size_gb": True}, "bad_size"),
        ({"user": "has space"}, "bad_user"),
        ({"user": ""}, "bad_user"),
        ({"secret": "tooshort"}, "bad_secret"),
        ({"secret": "has a space in it"}, "bad_secret"),
        ({"secret": "x" * 17}, "bad_secret"),
        ({"secret": ""}, "bad_secret"),
        ({"allow": "not-an-address"}, "bad_allow"),
        ({"folder": "/etc"}, "bad_folder"),
        ({"folder": str(box["share"] / "missing")}, "bad_folder"),
        ({"folder": str(box["tmp"] / "data")}, "bad_folder"),
    ]:
        with pytest.raises(it.DiskError) as bad:
            it.clean(_disk(**{"folder": folder, **change}))
        assert bad.value.key == key, change
    ok = it.clean(_disk(folder=folder, name=" VM-Disk ", allow="192.168.1.0/24"))
    assert (ok["name"], ok["allow"], ok["folder"]) == ("vm-disk", "192.168.1.0/24", folder)
    assert it.clean(_disk(folder=folder, allow=" 192.168.1.20 "))["allow"] == "192.168.1.20"
    broken = box["tmp"] / "pool" / "two\nlines"
    broken.mkdir()
    with pytest.raises(it.DiskError):  # a new line in a folder's name is refused
        it.clean(_disk(folder=str(broken)))


def test_a_disk_keeps_its_place_grows_and_never_shrinks(box):
    folder = str(box["share"])
    made = it.save(_disk(folder=folder, size_gb=2))
    with pytest.raises(it.DiskError) as taken:
        it.save(_disk(folder=folder))
    assert taken.value.key == "name_taken"
    grown = it.save(_disk(name="other-name", folder="/etc", size_gb=3, user="ben", secret=""), made["id"])
    assert (grown["name"], grown["folder"], grown["user"], grown["size_gb"]) == ("vm-disk", folder, "ben", 3)
    assert it.unseal(grown["secret"]) == "secretsecret12"  # no new password sent: the old one stays
    assert os.path.getsize(it.file_of(grown)) == 3 * GIB and grown["created"] == made["created"]
    with pytest.raises(it.DiskError) as smaller:
        it.save(_disk(size_gb=1), made["id"])
    assert smaller.value.key == "no_shrink" and os.path.getsize(it.file_of(grown)) == 3 * GIB
    changed = it.save(_disk(size_gb=3, secret="newsecretnew12"), made["id"])
    assert it.unseal(changed["secret"]) == "newsecretnew12"
    with pytest.raises(KeyError):
        it.save(_disk(), "nope")


def test_a_file_that_is_already_there_is_never_replaced(box):
    theirs = box["share"] / "vm-disk.iscsi.img"
    theirs.write_bytes(b"someone's data")
    with pytest.raises(it.DiskError) as exists:
        it.save(_disk(folder=str(box["share"])))
    assert exists.value.key == "file_exists" and theirs.read_bytes() == b"someone's data" and it.disks() == []


def test_the_most_disks_and_taking_one_off(box, monkeypatch):
    monkeypatch.setattr(it, "MAX_DISKS", 2)
    folder = str(box["share"])
    a = it.save(_disk(folder=folder, name="a"))
    b = it.save(_disk(folder=folder, name="b"))
    with pytest.raises(it.DiskError) as full:
        it.save(_disk(folder=folder, name="c"))
    assert full.value.key == "too_many" and full.value.params == {"value": 2}
    assert it.delete(a["id"])["name"] == "a" and os.path.exists(it.file_of(a))  # the file holds someone's data
    assert it.delete(b["id"], with_file=True)["name"] == "b" and not os.path.exists(it.file_of(b))
    assert it.delete("nope") is None and it.disks() == []


def test_the_services_file(box):
    folder = str(box["share"])
    odd = box["tmp"] / "pool" / "it's odd"
    odd.mkdir()
    it.save(_disk(folder=folder))
    it.save(_disk(folder=str(odd), name="only-me", user="ben", secret="p'ss\"word$1234", allow="192.0.2.5"))
    it.save(_disk(folder=folder, name="second"))  # the same user name and password as the first
    mark = it.write_conf()
    path = os.path.join(it.CONF_DIR, it.CONF_NAME)
    assert oct(os.stat(path).st_mode & 0o777) == "0o600" and oct(os.stat(it.CONF_DIR).st_mode & 0o777) == "0o700"
    with open(path, encoding="utf-8") as f:
        text = f.read()
    lines = text.splitlines()
    assert lines[0] == "#!/bin/sh" and lines[2] == "set -e" and lines[3] == "t='tgtadm --lld iscsi'"
    assert "$t --mode target --op new --tid 1 --targetname iqn.2026-11.net.kiboto:nas:vm-disk" in lines
    # quoted for the shell: a space, an apostrophe, a quote and a dollar sign are only text
    assert (
        f"$t --mode logicalunit --op new --tid 1 --lun 1 --backing-store '{folder}/vm-disk.iscsi.img' --bsoflags sync"
        in lines
    )
    assert "it'\"'\"'s odd/only-me.iscsi.img' --bsoflags sync" in text
    assert "$t --mode account --op new --user ben --password 'p'\"'\"'ss\"word$1234'" in lines
    assert text.count("--mode account --op new") == 2  # ana once, though two disks use the name
    assert text.count("--mode account --op bind") == 3
    assert "$t --mode target --op bind --tid 2 --initiator-address 192.0.2.5" in lines
    assert text.count("--initiator-address ALL") == 2
    assert it.write_conf() == mark  # the same disks: the same mark, so the service is not restarted
    it.save(_disk(size_gb=1, user="carl", secret="newsecretnew12"), it.disks()[0]["id"])
    assert it.write_conf() != mark  # a new password: a new mark


def test_one_user_name_has_one_password(box):
    folder = str(box["share"])
    first = it.save(_disk(folder=folder))
    with pytest.raises(it.DiskError) as clash:
        it.save(_disk(folder=folder, name="other", secret="differentpass12"))
    assert clash.value.key == "user_taken" and not os.path.exists(box["share"] / "other.iscsi.img")
    second = it.save(_disk(folder=folder, name="other"))  # the same password: fine
    with pytest.raises(it.DiskError):
        it.save(_disk(size_gb=1, secret="differentpass12"), second["id"])  # would split from the first
    assert it.save(_disk(size_gb=1, user="ben", secret="differentpass12"), second["id"])["user"] == "ben"
    assert it.save(_disk(size_gb=1, secret=""), first["id"])["user"] == "ana"  # itself is not "another disk"


def test_where_a_path_is_on_the_host():
    assert it.host_path(ME, "/mnt/user/My Files") == "/mnt/user/My Files"
    assert it.host_path(ME, "/data/iscsi/setup.sh") == "/host/appdata/kiboto/iscsi/setup.sh"
    assert it.host_path(ME, "/data/deep/x") == "/host/appdata/kiboto/deep/x"  # the longest mount that holds it
    assert it.host_path(ME, "/database") is None and it.host_path({}, "/data") is None


def test_the_container(box, monkeypatch):
    monkeypatch.setattr(it, "CONF_DIR", "/data/iscsi")
    kept = [{"name": "a", "folder": "/mnt/user/My Files"}, {"name": "b", "folder": "/mnt/user/My Files"}]
    want = it.desired(ME, kept, "abc")
    host = want["HostConfig"]
    assert want["Image"] == "ghcr.io/example/kiboto:sha-abc" and want["Entrypoint"] == ["sh", "-c"]
    assert "tgtd -f" in want["Cmd"][0] and "sh /etc/kiboto-iscsi/setup.sh" in want["Cmd"][0]
    assert "tgt-admin" not in want["Cmd"][0]  # the package's Perl helper is not in the image
    assert (
        host["NetworkMode"] == "host"
        and host["ReadonlyRootfs"] is True
        and host["RestartPolicy"] == {"Name": "unless-stopped"}
    )
    assert host["Binds"] == [
        "/host/appdata/kiboto/iscsi/setup.sh:/etc/kiboto-iscsi/setup.sh:ro",
        "/mnt/user/My Files:/mnt/user/My Files",
    ]
    assert "Privileged" not in host and "CapAdd" not in host  # it needs no special rights
    assert it.desired(ME, kept, "other")["Labels"]["kiboto.config"] != want["Labels"]["kiboto.config"]
    assert it.desired(ME, [{"name": "c", "folder": "/somewhere/else"}], "abc") is None


def test_ensure_starts_it_only_when_on_and_with_a_disk(box, monkeypatch):
    calls = box["calls"]
    folder = str(box["share"])
    assert it.ensure()["running"] is False and not [c for c in calls if c[0] == "POST"]
    it.save(_disk(folder=folder))
    assert it.ensure()["running"] is False  # a disk, and still off
    it.set_enabled(True)
    monkeypatch.setattr(it, "host_path", lambda me, path: path)
    out = it.ensure()
    made = [c for c in calls if c[0] == "POST" and "create" in c[1]]
    assert out["running"] is True and len(made) == 1 and made[0][3] == it.ELEVATED
    assert out["disks"][0]["name"] == "vm-disk" and out["port"] == 3260 and out["error"] == ""
    # running with the same disks: left alone
    box["container"] = {"Config": {"Labels": made[0][2]["Labels"]}, "State": {"Running": True}}
    calls.clear()
    assert it.ensure()["running"] is True and not [c for c in calls if c[0] != "GET"]
    # a change: made anew
    it.save(_disk(size_gb=1, secret="newsecretnew12"), it.disks()[0]["id"])
    calls.clear()
    it.ensure()
    assert [c[1] for c in calls if c[0] == "DELETE"] and [c for c in calls if "create" in c[1]]
    # turned off: removed
    it.set_enabled(False)
    calls.clear()
    assert it.ensure()["running"] is False and [c[1] for c in calls if c[0] == "DELETE"]


def test_what_is_said_when_it_cannot_run(box, monkeypatch):
    it.save(_disk(folder=str(box["share"])))
    it.set_enabled(True)
    assert "could not be reached" not in it.ensure()["error"]
    assert it.ensure()["error"] == "A disk's folder is not one the app engine can reach."  # ME has no such mount
    assert it.ensure()["why"] == "folder"
    box["container"] = {"State": {"Running": False}}
    assert "Port 3260 may be in use" in it.status()["error"] and it.status()["why"] == "down"
    box["container"] = {"State": {"Running": True, "Restarting": True}}
    assert it.status()["running"] is False
    monkeypatch.setattr(it, "_docker", lambda *a, **k: (0, None))
    assert it.status()["error"] == it.NO_DOCKER and it.ensure()["error"] == it.NO_DOCKER
    assert it.status()["why"] == "engine" and it.ensure()["why"] == "engine"


def test_the_api(box, client, auth_headers, monkeypatch):
    logged = []
    from backend import users_db

    monkeypatch.setattr(users_db, "log_security_event", lambda event, status, **k: logged.append(event))
    monkeypatch.setattr(it, "host_path", lambda me, path: path)
    assert client.get("/api/iscsi", headers=auth_headers).json()["enabled"] is False
    on = client.put("/api/iscsi/enabled", json={"enabled": True}, headers=auth_headers).json()
    assert on["enabled"] is True and on["running"] is False and on["disks"] == []  # nothing to serve yet
    made = client.post("/api/iscsi/disks", json=_disk(folder=str(box["share"])), headers=auth_headers).json()
    one = made["disks"][0]
    assert made["running"] is True and one["name"] == "vm-disk" and "secret" not in one and one["file_there"] is True
    bad = client.post(
        "/api/iscsi/disks", json=_disk(folder=str(box["share"]), name="other", secret="short"), headers=auth_headers
    )
    assert bad.status_code == 400 and bad.json()["error"] == "iscsi_bad_secret"
    assert bad.json()["text"]["msg_key"] == "srv.iscsi_bad_secret"
    big = client.post(
        "/api/iscsi/disks", json=_disk(folder=str(box["share"]), name="big", size_gb=10**7), headers=auth_headers
    )
    assert big.json()["text"]["params"] == {"value": it.MAX_GB}
    grown = client.put(f"/api/iscsi/disks/{one['id']}", json=_disk(size_gb=2, secret=""), headers=auth_headers).json()
    assert grown["disks"][0]["size_gb"] == 2
    assert client.put("/api/iscsi/disks/nope", json=_disk(), headers=auth_headers).status_code == 404
    gone = client.delete(f"/api/iscsi/disks/{one['id']}", headers=auth_headers).json()
    assert gone["disks"] == [] and os.path.exists(one["file"])  # the file stays
    assert client.delete(f"/api/iscsi/disks/{one['id']}", headers=auth_headers).json()["error"] == "iscsi_not_found"
    assert [e for e in logged if e.startswith("iscsi.")] == ["iscsi.switch", "iscsi.save", "iscsi.save", "iscsi.delete"]
    monkeypatch.setattr(
        "backend.auth.get_current_session",
        lambda tok: {
            "user_id": "u",
            "username": "sam",
            "role_id": "user",
            "scopes": ["storage:read", "shares:user_write"],
        },
    )
    for method, path in (("get", "/api/iscsi"), ("put", "/api/iscsi/enabled"), ("post", "/api/iscsi/disks")):
        res = client.request(method, path, json={"enabled": True}, headers={"Authorization": "Bearer x"})
        assert res.status_code == 403, (method, path)


@pytest.mark.real_confirmations
def test_turning_on_saving_and_removing_are_confirmed(box, client, auth_headers):
    for method, path, body, action in (
        ("put", "/api/iscsi/enabled", {"enabled": True}, "iscsi.enable"),
        ("post", "/api/iscsi/disks", _disk(folder=str(box["share"])), "iscsi.save"),
        ("delete", "/api/iscsi/disks/x", None, "iscsi.delete"),
    ):
        ask = client.request(method, path, json=body, headers=auth_headers)
        assert ask.status_code == 428 and ask.json()["action"] == action, path
    assert it.enabled() is False and it.disks() == []
    assert (
        client.put("/api/iscsi/enabled", json={"enabled": False}, headers=auth_headers).status_code == 200
    )  # off never asks


def test_at_start_it_is_brought_back_only_when_on(box, monkeypatch):
    ran = []
    monkeypatch.setattr(it, "ensure", lambda: ran.append(1))
    it.ensure_soon()
    for t in __import__("threading").enumerate():
        if t.name == "iscsi":
            t.join(5)
    assert ran == []
    it.set_enabled(True)
    it.ensure_soon()
    for t in __import__("threading").enumerate():
        if t.name == "iscsi":
            t.join(5)
    assert ran == [1]
