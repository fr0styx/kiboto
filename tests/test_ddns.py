"""Audit A8: Dynamic DNS for DuckDNS and Cloudflare, off by default, token sealed and never shown."""

import json

import pytest

from backend.services import ddns


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setattr(ddns, "STATE_FILE", str(tmp_path / "ddns.json"))


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, json.loads(body) if body else None))
        for (m, part), answer in self.routes.items():
            if m == method and part in url:
                return answer
        return 404, "{}"


def test_off_by_default_and_the_token_is_never_shown():
    st = ddns.public_state()
    assert st["enabled"] is False and st["token_set"] is False and "token" not in st
    saved = ddns.save(False, "duckdns", "home", "secret-token")
    assert saved["hostname"] == "home.duckdns.org" and saved["token_set"] is True and "token" not in saved
    with open(ddns.STATE_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["token"].startswith("enc2:") and "secret-token" not in raw["token"]
    assert ddns.save(False, "duckdns", "home", None)["token_set"] is True  # None keeps it
    assert ddns.save(False, "duckdns", "home", "")["token_set"] is False  # "" clears it


def test_settings_that_cannot_work_are_refused_in_words():
    with pytest.raises(ValueError, match="DuckDNS or Cloudflare"):
        ddns.save(False, "noip", "x.example.com", "t")
    with pytest.raises(ValueError, match="can't be used"):
        ddns.save(False, "cloudflare", "bad_name!.example.com", "t")
    with pytest.raises(ValueError, match="can't be used"):
        ddns.save(False, "duckdns", "home.example.com", "t")
    with pytest.raises(ValueError, match="before turning it on"):
        ddns.save(True, "cloudflare", "nas.example.com", "")
    assert not ddns.valid_hostname("cloudflare", "localhost")


def test_duckdns_update_records_the_ip_and_a_refusal_is_said():
    ddns.save(True, "duckdns", "home", "tok")
    http = FakeHttp({("GET", "duckdns.org/update"): (200, "OK\n203.0.113.7\n\nUPDATED")})
    st = ddns.run_once(now=1000.0, http=http)
    assert st["last_ip"] == "203.0.113.7" and st["last_error"] == "" and st["last_ok"] == 1000.0
    assert "domains=home" in http.calls[0][1] and "token=tok" in http.calls[0][1]
    st = ddns.run_once(now=2000.0, http=FakeHttp({("GET", "duckdns.org/update"): (200, "KO")}))
    assert "DuckDNS refused" in st["last_error"] and st["last_ip"] == "203.0.113.7"


def test_cloudflare_updates_the_record_only_when_the_ip_changed():
    ddns.save(True, "cloudflare", "nas.example.com", "cf-token")
    routes = {
        ("GET", "cdn-cgi/trace"): (200, "fl=1\nip=198.51.100.4\nts=1"),
        ("GET", "/zones?per_page"): (
            200,
            json.dumps(
                {"success": True, "result": [{"id": "z1", "name": "example.com"}, {"id": "z0", "name": "other.org"}]}
            ),
        ),
        ("GET", "/dns_records?"): (200, json.dumps({"success": True, "result": [{"id": "r1"}]})),
        ("PATCH", "/dns_records/r1"): (200, json.dumps({"success": True})),
    }
    http = FakeHttp(routes)
    st = ddns.run_once(now=1.0, http=http)
    assert st["last_ip"] == "198.51.100.4" and st["last_error"] == ""
    patch = [c for c in http.calls if c[0] == "PATCH"][0]
    assert patch[3] == {"content": "198.51.100.4"} and patch[2]["Authorization"] == "Bearer cf-token"
    http2 = FakeHttp(routes)
    ddns.run_once(now=400.0, http=http2)
    assert [c[0] for c in http2.calls] == ["GET"]  # same IP: only the address check


def test_cloudflare_creates_a_missing_record_and_explains_a_bad_token():
    ddns.save(True, "cloudflare", "nas.example.com", "cf-token")
    routes = {
        ("GET", "cdn-cgi/trace"): (200, "ip=198.51.100.9"),
        ("GET", "/zones?per_page"): (
            200,
            json.dumps({"success": True, "result": [{"id": "z1", "name": "example.com"}]}),
        ),
        ("GET", "/dns_records?"): (200, json.dumps({"success": True, "result": []})),
        ("POST", "/dns_records"): (200, json.dumps({"success": True})),
    }
    http = FakeHttp(routes)
    assert ddns.run_once(now=1.0, http=http)["last_error"] == ""
    post = [c for c in http.calls if c[0] == "POST"][0]
    assert post[3]["type"] == "A" and post[3]["name"] == "nas.example.com" and post[3]["proxied"] is False
    ddns.save(True, "cloudflare", "nas.other.net", None)
    st = ddns.run_once(now=2.0, http=FakeHttp({**routes, ("GET", "/zones?per_page"): (403, "{}")}))
    assert "refused the token" in st["last_error"]
    st = ddns.run_once(now=3.0, http=FakeHttp(routes))
    assert "None of the domains" in st["last_error"]
    st = ddns.run_once(now=4.0, http=FakeHttp({("GET", "cdn-cgi/trace"): (200, "nothing")}))
    assert "public address" in st["last_error"]


def test_due_only_while_on_and_every_five_minutes():
    assert ddns.due(10_000.0) is False
    ddns.save(True, "duckdns", "home", "tok")
    assert ddns.due(10_000.0) is True
    ddns.run_once(now=10_000.0, http=FakeHttp({("GET", "duckdns.org"): (200, "OK\n1.2.3.4")}))
    assert ddns.due(10_100.0) is False and ddns.due(10_301.0) is True
    st = ddns.run_once(now=20_000.0, http=lambda *a: (_ for _ in ()).throw(OSError("down")))
    assert st["last_error"] == "The provider could not be reached."


def test_routes(client, auth_headers, monkeypatch):
    assert client.get("/api/network/ddns", headers=auth_headers).json()["enabled"] is False
    res = client.put(
        "/api/network/ddns",
        headers=auth_headers,
        json={"enabled": True, "provider": "duckdns", "hostname": "home", "token": "t"},
    )
    assert res.status_code == 200 and res.json()["hostname"] == "home.duckdns.org" and "token" not in res.json()
    bad = client.put(
        "/api/network/ddns",
        headers=auth_headers,
        json={"enabled": True, "provider": "duckdns", "hostname": "x.example.com"},
    )
    assert bad.status_code == 400 and "can't be used" in bad.json()["detail"]
    monkeypatch.setattr(ddns, "_http", lambda *a: (200, "OK\n203.0.113.1"))
    monkeypatch.setattr(ddns.run_once, "__defaults__", (None, ddns._http))
    assert client.post("/api/network/ddns/update", headers=auth_headers).json()["last_ip"] == "203.0.113.1"
