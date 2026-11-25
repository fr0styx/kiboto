"""ADR 0007 step 2: the family portal goes on the internet through Funnel on the share links' port,
next to the share links and nothing else; the owner's routes; the join link."""

import pytest

from backend import rate_limit
from backend.services import family_portal, public_links, tailnet_ports

DNS = "attic.example-tailnet.ts.net"
READY = {"ready": True, "connected": True, "https": True, "funnel": True, "headscale": False, "ports": [8443]}


class FakeTailscale:
    def __init__(self, monkeypatch, handlers=None, ready=READY, public=True):
        self.handlers = dict(handlers or {})
        self.public, self.calls = public, []
        monkeypatch.setattr(public_links, "dns_name", lambda: DNS)
        monkeypatch.setattr(public_links, "funnel_readiness", lambda *a: dict(ready))
        monkeypatch.setattr(public_links, "port_state", lambda dns: (dict(self.handlers), self.public, True))
        monkeypatch.setattr(public_links, "immich_to_move", lambda dns=None: "")
        monkeypatch.setattr(public_links, "tailscale", self.run)

    def run(self, args, timeout=8.0):
        self.calls.append(args)
        path = next((a.split("=", 1)[1] for a in args if a.startswith("--set-path=")), "")
        if args[-1] == "off":
            self.handlers.pop(path, None)
        else:
            self.handlers[path] = {"Proxy": args[-1]}
        return 0, ""


@pytest.fixture
def portal(tmp_path, monkeypatch):
    monkeypatch.setattr(family_portal, "STATE_FILE", str(tmp_path / "family_portal.json"))
    family_portal.end_sessions()
    rate_limit.reset()
    return family_portal


def test_publishing_puts_only_portal_on_the_share_links_port(portal, monkeypatch):
    ts = FakeTailscale(monkeypatch)
    out = portal.publish(8082)
    assert out["ok"] and portal.is_on()
    assert ts.calls[-1] == [
        "funnel",
        "--bg",
        "--yes",
        "--https=8443",
        "--set-path=/portal",
        "http://127.0.0.1:8082/portal",
    ]
    assert portal.live() and portal.address() == f"https://{DNS}:8443/portal/"


def test_share_links_and_the_portal_share_the_port_but_nothing_else_may(portal, monkeypatch):
    FakeTailscale(monkeypatch, handlers={tailnet_ports.SHARE_PATH: {}})
    assert portal.publish(8082)["ok"]
    assert public_links._others({"/portal": {}, "/api/fs/shared": {}}) == []
    portal.set_on(False)
    FakeTailscale(monkeypatch, handlers={"/": {"Proxy": "http://127.0.0.1:2283"}})  # Immich in the tailnet
    out = portal.publish(8082)
    assert not out["ok"] and out["error"] == public_links.OTHERS_ON_PORT and not portal.is_on()


def test_nothing_is_published_until_the_tailnet_owner_allowed_funnel(portal, monkeypatch):
    ts = FakeTailscale(monkeypatch, ready={**READY, "ready": False, "funnel": False})
    out = portal.publish(8082)
    assert not out["ok"] and out["funnel"]["funnel"] is False and ts.calls == [] and not portal.is_on()


def test_off_takes_it_down_and_says_so_only_when_tailscale_shows_it(portal, monkeypatch):
    ts = FakeTailscale(monkeypatch)
    portal.publish(8082)
    out = portal.unpublish()
    assert out["ok"] and not portal.is_on() and "/portal" not in ts.handlers
    stuck = FakeTailscale(monkeypatch, handlers={"/portal": {}})
    stuck.run = lambda args, timeout=8.0: (0, "")  # Tailscale ignores the request
    monkeypatch.setattr(public_links, "tailscale", stuck.run)
    assert portal.unpublish() == {"ok": False, "error": family_portal.NOT_OFF}


def test_the_owner_routes(client, auth_headers, portal, monkeypatch):
    FakeTailscale(monkeypatch)
    from backend.users_db import create_user, get_user_by_username

    if not get_user_by_username("portal_gran"):
        create_user("portal_gran", "Gran", "a-long-password-1", role_id="share_user")
    gran = get_user_by_username("portal_gran")
    view = client.get("/api/network/family-portal", headers=auth_headers).json()
    assert view["on"] is False and view["address"] == f"https://{DNS}:8443/portal/"
    assert any(p["username"] == "portal_gran" and not p["allowed"] for p in view["people"])

    r = client.post(f"/api/network/family-portal/people/{gran['id']}/invite", headers=auth_headers)
    assert r.status_code == 400  # not allowed yet
    r = client.put(f"/api/network/family-portal/people/{gran['id']}", json={"allowed": True}, headers=auth_headers)
    assert any(p["id"] == gran["id"] and p["allowed"] for p in r.json()["people"])
    link = client.post(f"/api/network/family-portal/people/{gran['id']}/invite", headers=auth_headers).json()
    assert link["link"].startswith(f"https://{DNS}:8443/portal/#join=") and link["days"] == 7
    assert family_portal.invite_user(link["token"]) is None  # a join link works only while the portal is on

    on = client.put("/api/network/family-portal", json={"on": True}, headers=auth_headers).json()
    assert on["ok"] and on["on"] and on["live"]
    assert family_portal.invite_user(link["token"])["id"] == gran["id"]
    off = client.put("/api/network/family-portal", json={"on": False}, headers=auth_headers).json()
    assert off["ok"] and not off["on"]


@pytest.mark.real_confirmations
def test_turning_it_on_is_confirmed_first(client, auth_headers, portal, monkeypatch):
    ts = FakeTailscale(monkeypatch)
    r = client.put("/api/network/family-portal", json={"on": True}, headers=auth_headers)
    assert r.status_code == 428 and ts.calls == [] and not portal.is_on()


def test_someone_without_settings_rights_cannot_change_it(client, portal, monkeypatch):
    from backend.auth import create_session
    from backend.users_db import create_user, get_user_by_username

    FakeTailscale(monkeypatch)
    if not get_user_by_username("portal_kid"):
        create_user("portal_kid", "Kid", "a-long-password-1", role_id="share_user")
    headers = {"Authorization": f"Bearer {create_session('portal_kid')}"}
    assert client.put("/api/network/family-portal", json={"on": True}, headers=headers).status_code == 403


def test_the_outside_summary_names_the_portal_and_flags_what_was_not_turned_on():
    from backend.services import exposure

    both = [{"port": 8443, "owner": "share_links", "paths": ["/api/fs/shared", "/portal"], "targets": []}]
    portal_only = [{"port": 8443, "owner": "share_links", "paths": ["/portal"], "targets": []}]
    x = exposure.judge("Running", False, portal_only, False, set(), None, portal_on=True)
    assert x["family_portal"] and not x["share_links"] and x["tone"] == "neutral" and x["level"] == "public"
    x = exposure.judge("Running", False, portal_only, True, set(), None, portal_on=False)
    assert x["unexpected"] == [8443] and x["tone"] == "red"  # the portal is public but Kiboto has it off
    x = exposure.judge("Running", False, both, True, set(), None, portal_on=True)
    assert x["share_links"] and x["family_portal"] and x["unexpected"] == []
    x = exposure.judge("Running", False, both, True, set(), None, portal_on=False)
    assert x["unexpected"] == [8443]
