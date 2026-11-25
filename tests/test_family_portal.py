"""ADR 0007: the family portal. Off by default; a join link makes a portal-only passkey; sign-in is
by passkey; its sessions reach nothing but /portal; files are a person's own, whatever their role."""

import time

import pytest

from backend import config, rate_limit
from backend.services import family_portal, passkeys, share_access
from tests.test_passkeys import HOST, ORIGIN, FakeAuthenticator

H = {"host": HOST, "origin": ORIGIN}


@pytest.fixture
def portal(tmp_path, monkeypatch):
    monkeypatch.setattr(family_portal, "STATE_FILE", str(tmp_path / "family_portal.json"))
    family_portal.end_sessions()
    rate_limit.reset()
    yield family_portal
    family_portal.end_sessions()
    rate_limit.reset()


def _person(name, role="share_user"):
    from backend.users_db import create_user, get_user_by_username

    if not get_user_by_username(name):
        create_user(name, name.title(), "a-long-password-1", role_id=role)
    user = get_user_by_username(name)
    passkeys.forget_user(user["id"])
    return user


def _join(client, portal, user):
    portal.set_on(True)
    portal.allow(user["id"], True)
    token = portal.make_invite(user["id"])
    opts = client.post("/portal/api/join/options", json={"token": token}, headers=H)
    assert opts.status_code == 200, opts.text
    phone = FakeAuthenticator()
    body = opts.json()
    done = client.post(
        "/portal/api/join/finish",
        json={"token": token, "ticket": body["ticket"], "credential": phone.create(body["options"])},
        headers=H,
    )
    assert done.status_code == 200, done.text
    return phone, token


def test_off_by_default(client, portal):
    assert client.get("/portal/api/state", headers=H).json() == {"on": False, "signed_in": False, "name": ""}
    assert client.post("/portal/api/signin/options", headers=H).status_code == 404
    assert client.get("/portal/api/list", headers=H).status_code == 404


def test_a_join_link_makes_a_portal_only_passkey_and_signs_in_once(client, portal):
    ann = _person("portal_ann")
    phone, token = _join(client, portal, ann)
    assert client.get("/portal/api/state", headers=H).json()["signed_in"] is True
    [pk] = passkeys.list_for(ann["id"])
    assert pk["portal_only"] is True and pk["rp_id"] == HOST
    assert not passkeys.has_passkeys(ann["id"])  # it doesn't count as two-step sign-in for Kiboto itself
    # the link was used
    assert client.post("/portal/api/join/options", json={"token": token}, headers=H).status_code == 401
    # Kiboto's own sign-in refuses the portal's passkey
    opts = passkeys.login_options(HOST)
    with pytest.raises(passkeys.PasskeyError, match="family portal only"):
        passkeys.login_finish(opts["ticket"], phone.get(opts["options"]))


def test_signing_in_with_the_passkey(client, portal, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app

    ann = _person("portal_ann2")
    phone, _ = _join(client, portal, ann)
    fresh = TestClient(app)
    opts = fresh.post("/portal/api/signin/options", headers=H).json()
    done = fresh.post(
        "/portal/api/signin/finish",
        json={"ticket": opts["ticket"], "credential": phone.get(opts["options"])},
        headers=H,
    )
    assert done.status_code == 200 and done.json()["name"] == "Portal_Ann2"
    assert fresh.get("/portal/api/state", headers=H).json()["signed_in"] is True
    # someone no longer allowed can't sign in, even with a good passkey
    portal.allow(ann["id"], False)
    portal.allow(ann["id"], True)  # allowed again later: the old sessions stay ended
    assert fresh.get("/portal/api/state", headers=H).json()["signed_in"] is False


def test_the_main_api_refuses_a_portal_session(client, portal):
    ann = _person("portal_ann3")
    _join(client, portal, ann)
    token = client.cookies.get("kiboto_portal")
    assert token and token.startswith("zpt_")
    from backend.auth import get_current_session

    assert get_current_session(token) is None
    r = client.get("/api/fs/browse", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


@pytest.fixture
def tree(tmp_path, monkeypatch):
    root = tmp_path / "user"
    for d in ("media", "homes/portal_boss", "homes/someone", "appdata/app"):
        (root / d).mkdir(parents=True)
    (root / "homes" / "portal_boss" / "photo.txt").write_text("mine")
    (root / "homes" / "someone" / "secret.txt").write_text("theirs")
    (root / "appdata" / "app" / "config.txt").write_text("system")
    (root / "media" / "song.mp3").write_text("x")
    monkeypatch.setattr(config, "POOL_PATH", str(root))
    monkeypatch.setattr("backend.config.ALLOWED_BROWSE_ROOTS", [str(root)])
    for mod in ("backend.api.files.common", "backend.api.files.browse", "backend.services.path_access"):
        monkeypatch.setattr(f"{mod}.ALLOWED_BROWSE_ROOTS", [str(root)], raising=False)
    monkeypatch.setattr(
        share_access, "known_shares", lambda: [{"name": "media", "path": str(root / "media"), "samba": None}]
    )
    share_access.invalidate()
    return root


def test_an_administrator_sees_only_their_own_files_on_the_portal(client, portal, tree):
    boss = _person("portal_boss", role="superadmin")
    _join(client, portal, boss)

    def get(route, path):
        return client.get(f"/portal/api/{route}", params={"path": str(path)}, headers=H)

    own = get("file", tree / "homes" / "portal_boss" / "photo.txt")
    assert own.status_code == 200 and own.content == b"mine"
    assert "attachment" in own.headers["content-disposition"]
    for path in (
        tree / "homes" / "someone" / "secret.txt",
        tree / "homes" / "portal_boss" / ".." / "someone" / "secret.txt",
        tree / "appdata" / "app" / "config.txt",
        tree / "media" / "song.mp3",  # a share not granted to them
    ):
        assert get("file", path).status_code == 403, path
    assert get("list", tree / "appdata").status_code == 403
    assert get("list", tree / "homes" / "someone").status_code == 403
    listed = get("list", tree / "homes" / "portal_boss").json()
    assert [e["name"] for e in listed["dirs"] if e["name"] != ".."] == ["photo.txt"]


def test_sessions_end_when_off_idle_or_too_old(portal, monkeypatch):
    ann = _person("portal_ann4")
    portal.set_on(True)
    portal.allow(ann["id"], True)
    token = portal.start_session(ann["id"])
    assert portal.session_user(token)["id"] == ann["id"]
    portal.set_on(False)
    assert portal.session_user(token) is None
    portal.set_on(True)
    token = portal.start_session(ann["id"])
    now = time.time()
    monkeypatch.setattr(family_portal.time, "time", lambda: now + family_portal.SESSION_IDLE_SECS + 1)
    assert portal.session_user(token) is None
    token = portal.start_session(ann["id"])  # started at the moved clock
    for step in range(1, 30):  # used every 25 minutes, still ends after 12 hours
        moved = now + family_portal.SESSION_IDLE_SECS + 1 + step * 1500
        monkeypatch.setattr(family_portal.time, "time", lambda m=moved: m)
        if portal.session_user(token) is None:
            break
    assert step * 1500 >= family_portal.SESSION_MAX_SECS - 1500


def test_a_join_link_has_a_few_tries_and_a_week(portal, monkeypatch):
    ann = _person("portal_ann5")
    portal.set_on(True)
    with pytest.raises(ValueError):
        portal.make_invite(ann["id"])  # not allowed yet
    portal.allow(ann["id"], True)
    token = portal.make_invite(ann["id"])
    for _ in range(family_portal.INVITE_TRIES):
        assert portal.invite_user(token)["id"] == ann["id"]
    assert portal.invite_user(token) is None
    token = portal.make_invite(ann["id"])
    later = time.time() + family_portal.INVITE_SECS + 1
    monkeypatch.setattr(family_portal.time, "time", lambda: later)
    assert portal.invite_user(token) is None


def test_failed_sign_ins_lock_the_address_and_other_sites_are_refused(client, portal):
    portal.set_on(True)
    bad = {"ticket": "nope", "credential": {"id": "x", "rawId": "x"}}
    codes = [client.post("/portal/api/signin/finish", json=bad, headers=H).status_code for _ in range(11)]
    assert codes[0] in (400, 401) and codes[-1] == 429
    rate_limit.reset()
    evil = {"host": HOST, "origin": "https://evil.example"}
    assert client.post("/portal/api/signin/options", headers=evil).status_code == 403
