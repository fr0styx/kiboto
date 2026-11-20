"""High availability: the first NAS's apps on the second one. The first NAS tells how its apps are set up; the second keeps that sealed,
and after a takeover adds the ones whose folders it keeps, one by one, when asked."""

import copy
import json
import os

import pytest
import yaml

from backend import secret_box
from backend.services import compose_apply, ha_bring, ha_folders
from backend.services import ha_apps as hp
from backend.services import ha_link as ha
from backend.services import ha_state as hs

A, B = "http://192.168.1.10:8082", "http://192.168.1.20:8082"
REAL_SETUPS = hp.setups
JELLY = "services:\n  jellyfin:\n    image: example/jellyfin\n    volumes:\n    - /mnt/first/appdata/jellyfin:/config:rw\n    - /mnt/first/films:/media:ro\n"
SETUPS = [
    {
        "name": "jellyfin",
        "compose": JELLY,
        "folders": ["/mnt/first/appdata/jellyfin", "/mnt/first/films"],
        "images": ["example/jellyfin"],
    },
    {
        "name": "taxes",
        "compose": "services:\n  taxes:\n    image: example/taxes\n    volumes:\n    - /mnt/first/taxes:/data:rw\n",
        "folders": ["/mnt/first/taxes"],
        "images": ["example/taxes"],
    },
    {
        "name": "odd",
        "compose": "services:\n  odd:\n    image: example/odd\n    volumes:\n    - /var/lib/docker/volumes/odd/_data:/data:rw\n",
        "folders": ["/var/lib/docker/volumes/odd/_data"],
        "images": ["example/odd"],
    },
]
HERE = {
    "shares": {"appdata": "/mnt/tank/appdata", "films": "/mnt/tank/films"},
    "pools": [("/mnt/tank", "tank")],
    "first_paths": {"appdata": "/mnt/first/appdata", "films": "/mnt/first/films", "taxes": "/mnt/first/taxes"},
}


class Net:
    def __init__(self, tmp_path, monkeypatch):
        self.dirs = {A: tmp_path / "first", B: tmp_path / "second"}
        for d in self.dirs.values():
            d.mkdir()
        self.patch, self.me = monkeypatch, A
        monkeypatch.setattr(ha, "my_name", lambda: "First NAS" if self.me == A else "Second NAS")
        monkeypatch.setattr(ha, "audit", lambda *a: None)
        monkeypatch.setattr(ha, "_seen", {})
        monkeypatch.setattr(hp, "_adding", {})
        monkeypatch.setattr(hp, "setups", lambda: copy.deepcopy(SETUPS))
        monkeypatch.setattr(ha_bring, "here", lambda: HERE)
        monkeypatch.setattr(ha_folders, "chosen", lambda: ["appdata", "films"])
        self.on(A)

    def on(self, box):
        self.me = box
        self.patch.setattr(ha, "STATE_FILE", str(self.dirs[box] / "ha.json"))
        self.patch.setattr(hs, "DIR", str(self.dirs[box] / "ha"))
        self.patch.setattr(hp, "DIR", str(self.dirs[box] / "ha"))

    def send(self, url, body):
        back, target = self.me, next(box for box in self.dirs if url.startswith(box))
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
    code = ha.new_code("ana")["code"]
    made.on(B)
    ha.pair_with(A, code, B, "own", send=made.send)
    return made


class Now:
    """A thread that runs at once, so a test sees the result."""

    def __init__(self, target=None, args=(), name="", daemon=False):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def test_the_first_nas_tells_how_its_apps_are_set_up_without_kiboto_itself(monkeypatch):
    listed = [
        {"Id": "k" * 12, "Names": ["/kiboto"], "Labels": {}},
        {"Id": "a" * 12, "Names": ["/media-jellyfin-1"], "Labels": {"com.docker.compose.project": "media"}},
        {"Id": "b" * 12, "Names": ["/media-db-1"], "Labels": {"com.docker.compose.project": "media"}},
        {"Id": "c" * 12, "Names": ["/solo"], "Labels": {}},
        {"Id": "d" * 12, "Names": ["/gone"], "Labels": {}},
        {"Id": "e" * 12, "Names": ["/kiboto-sftp"], "Labels": {"managed-by": "kiboto"}},
        {"Id": "", "Names": ["/nameless"], "Labels": {}},
    ]
    inspects = {
        "a" * 12: {
            "Name": "/media-jellyfin-1",
            "Config": {"Image": "example/jellyfin"},
            "Mounts": [
                {"Type": "bind", "Source": "/mnt/first/appdata/jellyfin", "Destination": "/config"},
                {"Type": "volume", "Source": "/var/lib/docker/volumes/x/_data", "Destination": "/cache"},
            ],
        },
        "b" * 12: {
            "Name": "/media-db-1",
            "Config": {"Image": "example/db"},
            "Mounts": [{"Type": "bind", "Source": "/mnt/first/appdata/db", "Destination": "/var/lib/db"}],
        },
        "c" * 12: {"Name": "/solo", "Config": {"Image": "example/solo"}, "Mounts": []},
    }

    def docker(method, path, body=None, timeout=15.0, headers=None):
        if path.startswith("/containers/json"):
            return 200, listed
        cid = path.split("/")[2]
        return (200, inspects[cid]) if cid in inspects else (404, {})

    monkeypatch.setattr("backend.services.container_mutator.docker_request", docker)
    monkeypatch.setattr("backend.hardware.docker_stats.is_kiboto_own", lambda cid, name: name == "kiboto")
    monkeypatch.setattr(
        "backend.services.app_backup.compose_of",
        lambda found: "services: {" + ", ".join(str(i["Name"]).lstrip("/") + ": {}" for i in found) + "}",
    )
    said = hp.setups()
    # Kiboto itself is not an app, nor a helper it makes for itself, nor a container that vanished
    assert [a["name"] for a in said] == ["media", "solo"]
    media = said[0]
    assert media["folders"] == ["/mnt/first/appdata/db", "/mnt/first/appdata/jellyfin"]  # binds only
    assert media["images"] == ["example/db", "example/jellyfin"] and "media-db-1" in media["compose"]
    monkeypatch.setattr(hp, "MAX_TEXT", 10)
    assert hp.setups() == []  # more text than one answer may carry: left out, not cut
    monkeypatch.setattr("backend.services.container_mutator.docker_request", lambda *a, **k: (0, None))
    with pytest.raises(RuntimeError):
        hp.setups()  # Docker does not answer: not the same as having no apps


def test_the_second_nas_keeps_the_set_ups_sealed(net):
    assert hp.view() == {"apps_known": 0, "apps_at": None} and hp.kept() == []
    assert hp.fetch(send=net.send) == 3
    with open(os.path.join(hp.DIR, hp.KEPT)) as f:
        raw = f.read()
    assert (
        "jellyfin" not in raw and "/mnt/first" not in raw
    )  # a set-up holds an app's passwords: sealed where it is kept
    assert [a["name"] for a in hp.kept()] == ["jellyfin", "taxes", "odd"]
    assert hp.view()["apps_known"] == 3 and hp.view()["apps_at"] > 0
    net.on(A)
    assert hp.fetch(send=net.send) == 0  # a first NAS asks nothing
    with pytest.raises(ha.LinkError) as e:
        ha.call("apps_list", send=net.send)  # and a second NAS tells nothing
    assert e.value.key == "refused"


def test_an_app_is_pointed_at_this_boxes_folders_or_cannot_be_added(net, tmp_path):
    names = ["appdata", "films"]
    where, why = hp.placed(SETUPS[0], HERE, names)
    assert why == {} and where == {
        "/mnt/first/appdata/jellyfin": "/mnt/tank/appdata/jellyfin",
        "/mnt/first/films": "/mnt/tank/films",
    }
    assert hp.placed(SETUPS[1], HERE, names) == ({}, {"why": "folder_not_kept", "folder": "taxes"})
    assert hp.placed(SETUPS[0], HERE, ["films"])[1] == {"why": "folder_not_kept", "folder": "appdata"}
    assert hp.placed(SETUPS[2], HERE, names) == (
        {},
        {"why": "folder_missing", "path": "/var/lib/docker/volumes/odd/_data"},
    )
    same = {"name": "x", "folders": [str(tmp_path)]}  # outside the first NAS's shared folders, and this box has it
    assert hp.placed(same, HERE, names) == ({str(tmp_path): str(tmp_path)}, {})
    doc = yaml.safe_load(hp.repointed(JELLY, where))
    assert doc["services"]["jellyfin"]["volumes"] == [
        "/mnt/tank/appdata/jellyfin:/config:rw",
        "/mnt/tank/films:/media:ro",
    ]
    long_form = "services:\n  a:\n    volumes:\n    - {type: bind, source: /mnt/first/films, target: /m}\n    - named:/data\n  b: {}\nvolumes:\n  named: {}\n"
    doc = yaml.safe_load(hp.repointed(long_form, where))
    assert doc["services"]["a"]["volumes"] == [
        {"type": "bind", "source": "/mnt/tank/films", "target": "/m"},
        "named:/data",
    ]


def test_after_a_takeover_an_app_is_added_when_asked_and_everything_else_is_said(net, monkeypatch):
    hp.fetch(send=net.send)
    with pytest.raises(ha.LinkError) as e:
        hp.add("jellyfin", "own")
    assert e.value.key == "not_taken_over"
    monkeypatch.setattr(ha, "role", lambda: "took_over")
    monkeypatch.setattr(hp.threading, "Thread", Now)
    here: set[str] = set()
    monkeypatch.setattr(hp, "_here_already", lambda: set(here))
    applied = []
    monkeypatch.setattr(
        compose_apply, "build", lambda text, env, project, base: applied.append((project, text)) or {"project": project}
    )
    monkeypatch.setattr(compose_apply, "plan", lambda built, current, reasons: {"elevated": []})
    monkeypatch.setattr(compose_apply, "apply_built", lambda built, current, docker, ok, **k: {"ok": True})
    listed = {a["name"]: a for a in hp.listing()}
    assert listed["jellyfin"]["why"] is None and listed["jellyfin"]["state"] == ""
    assert listed["taxes"]["why"] == {"why": "folder_not_kept", "folder": "taxes"}
    assert "compose" not in json.dumps(listed)  # the screen never gets a set-up
    for name, key in (("taxes", "app_folders"), ("nobody", "no_app")):
        with pytest.raises(ha.LinkError) as e:
            hp.add(name, "own")
        assert e.value.key == key
    assert hp.add("jellyfin", "own") == {"state": "adding"}
    assert applied[0][0] == "jellyfin" and "/mnt/tank/appdata/jellyfin:/config:rw" in applied[0][1]
    assert "/mnt/first" not in applied[0][1]
    assert {a["name"]: a["state"] for a in hp.listing()}["jellyfin"] == "added"
    here.add("jellyfin")
    assert {a["name"]: a["state"] for a in hp.listing()}["jellyfin"] == "here"
    with pytest.raises(ha.LinkError) as e:
        hp.add("jellyfin", "own")
    assert e.value.key == "app_here"


def test_an_app_that_does_not_come_up_or_asks_for_the_host_is_said_so(net, monkeypatch):
    hp.fetch(send=net.send)
    monkeypatch.setattr(ha, "role", lambda: "took_over")
    monkeypatch.setattr(hp.threading, "Thread", Now)
    monkeypatch.setattr(hp, "_here_already", lambda: set())
    monkeypatch.setattr(compose_apply, "build", lambda text, env, project, base: {"project": project})
    monkeypatch.setattr(compose_apply, "plan", lambda built, current, reasons: {"elevated": []})
    monkeypatch.setattr(compose_apply, "apply_built", lambda *a, **k: {"ok": False, "error": "the image was not found"})
    state = lambda: {a["name"]: (a["state"], a["error"]) for a in hp.listing()}["jellyfin"]  # noqa: E731
    hp.add("jellyfin", "own")
    assert state() == ("failed", "the image was not found")
    monkeypatch.setattr(compose_apply, "plan", lambda built, current, reasons: {"elevated": ["jellyfin: privileged"]})
    hp.add("jellyfin", "own")  # a failed one can be tried again
    assert state() == ("needs_review", "")

    def broken(text, env, project, base):
        raise compose_apply.ComposeError("The file has no services.")

    monkeypatch.setattr(compose_apply, "build", broken)
    hp.add("jellyfin", "own")
    assert state() == ("failed", "The file has no services.")
    # while one is being added it says so, and is not started twice
    monkeypatch.setattr(hp.threading, "Thread", lambda **k: type("Later", (), {"start": lambda self: None})())
    hp.add("jellyfin", "own")
    assert state()[0] == "adding"
    with pytest.raises(ha.LinkError) as e:
        hp.add("jellyfin", "own")
    assert e.value.key == "app_here"


def test_the_names_this_box_has_already(monkeypatch):
    listed = [
        {"Names": ["/media-jellyfin-1"], "Labels": {"com.docker.compose.project": "media"}},
        {"Names": ["/solo"], "Labels": {}},
    ]
    monkeypatch.setattr("backend.services.container_mutator.docker_request", lambda *a, **k: (200, listed))
    assert hp._here_already() == {"media-jellyfin-1", "media", "solo"}
    monkeypatch.setattr("backend.services.container_mutator.docker_request", lambda *a, **k: (0, None))
    assert hp._here_already() == set()

    def no_docker(*a, **k):
        raise RuntimeError("Docker socket not reachable")

    monkeypatch.setattr("backend.services.container_mutator.docker_request", no_docker)
    assert hp._here_already() == set()


def test_a_first_nas_whose_docker_does_not_answer_says_so_and_the_second_keeps_what_it_has(net, monkeypatch):
    assert hp.fetch(send=net.send) == 3

    def no_docker(*a, **k):
        raise RuntimeError("Docker socket not reachable")

    for docker in (no_docker, lambda *a, **k: (500, None)):
        monkeypatch.setattr(hp, "setups", REAL_SETUPS)
        monkeypatch.setattr("backend.services.container_mutator.docker_request", docker)
        with pytest.raises(ha.LinkError) as e:
            hp.fetch(send=net.send)
        assert e.value.key == "refused" and "Docker" in str(e.value)
        assert [a["name"] for a in hp.kept()] == ["jellyfin", "taxes", "odd"]  # not replaced by "no apps"


def test_a_new_secret_key_and_unpairing(net, tmp_path, monkeypatch):
    from backend import config

    hp.fetch(send=net.send)
    old = str(config.SECRET_KEY)
    monkeypatch.setattr(config, "SECRET_KEY_FILE", str(tmp_path / "secret.key"))
    (tmp_path / "secret.key.previous").write_text(old)
    monkeypatch.setattr(config, "SECRET_KEY", "a-new-key-after-rotation")
    assert hp.reseal() == 1
    os.remove(tmp_path / "secret.key.previous")
    assert len(hp.kept()) == 3
    monkeypatch.setattr(config, "SECRET_KEY", "yet-another-key")
    assert hp.kept() == []  # sealed with a key that is gone: nothing is listed, nothing breaks
    monkeypatch.setattr(config, "SECRET_KEY", "a-new-key-after-rotation")
    hp._note("jellyfin", {"state": "added"})
    hp.forget()
    assert hp.kept() == [] and hp.view()["apps_known"] == 0 and hp.reseal() == 0 and hp._done() == {}
    assert hp.listing() == []


def test_the_nightly_fetch_asks_for_the_apps_too(net, monkeypatch):
    monkeypatch.setattr(hs, "_state", {"fetching": False, "error": "", "ran": ""})
    asked = []
    monkeypatch.setattr(hs, "fetch", lambda send=None: asked.append("settings") or {})
    monkeypatch.setattr(hp, "fetch", lambda send=None: asked.append("apps") or 3)
    monkeypatch.setattr(ha_folders, "fetch_all", lambda send=None: asked.append("folders") or {})
    monkeypatch.setattr(hs.threading, "Thread", Now)
    assert hs.fetch_soon() is True and asked == ["settings", "apps", "folders"]

    def older(send=None):
        raise ha.LinkError("refused", "The other NAS refused.")

    monkeypatch.setattr(hp, "fetch", older)  # a first NAS from before this question
    assert hs.fetch_soon() is True and hs.view()["fetch_error"] == ""


def test_over_the_api(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(ha, "STATE_FILE", str(tmp_path / "ha.json"))
    monkeypatch.setattr(hs, "DIR", str(tmp_path / "ha"))
    monkeypatch.setattr(hp, "DIR", str(tmp_path / "ha"))
    status = client.get("/api/ha", headers=auth_headers).json()
    assert status["apps_known"] == 0
    assert client.get("/api/ha/apps", headers=auth_headers).json() == {"apps": [], "at": None}
    res = client.post("/api/ha/apps/jellyfin/add", json={}, headers=auth_headers)
    assert res.status_code == 409 and res.json()["error"] == "ha_not_taken_over"
    assert res.json()["text"]["msg_key"] == "srv.ha_not_taken_over"
    assert client.post("/api/ha/apps/..%2Fx/add", json={}, headers=auth_headers).status_code in (404, 422)
    asked = []
    monkeypatch.setattr(hp, "add", lambda name, actor: asked.append(name) or {"state": "adding"})
    monkeypatch.setattr(hp, "listing", lambda: [{"name": "jellyfin", "state": "adding"}])
    said = client.post("/api/ha/apps/jellyfin/add", json={}, headers=auth_headers)
    assert said.status_code == 200 and said.json()["apps"][0]["state"] == "adding" and asked == ["jellyfin"]


def test_a_set_up_is_rebuilt_from_the_containers_and_a_stack_is_named_by_its_labels():
    from backend.services import app_backup, docker_stacks

    made = yaml.safe_load(app_backup.compose_of([]))
    assert made == {"services": {}}
    assert docker_stacks.stack_of({"com.docker.compose.project": "media"}) == "media"
    assert docker_stacks.stack_of({}) == "" and docker_stacks.stack_of(None) == ""
