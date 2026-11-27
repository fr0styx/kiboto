"""Audit A9: HTTPS at home through ACME over DNS; a fake ACME server checks every signed request."""

import base64
import datetime as dt
import json

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.x509.oid import NameOID

from backend.services import acme_dns, ddns


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(acme_dns, "TLS_DIR", str(tmp_path / "tls"))
    monkeypatch.setattr(acme_dns, "STATE_FILE", str(tmp_path / "tls" / "state.json"))
    monkeypatch.setattr(ddns, "STATE_FILE", str(tmp_path / "ddns.json"))


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _self_signed(name):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=90))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


class FakeAcme:
    D = "https://acme.test/dir"

    def __init__(self, bad_challenge=False, bad_nonces=0, proved=False):
        self.pem = _self_signed("home.duckdns.org")
        self.bad_nonces = bad_nonces  # how many requests are refused for their nonce first
        self.challenged = proved  # the name was proved lately: its authorization is valid already
        self.bad = bad_challenge
        self.posts = []
        self.account_jwk = None

    def _verify(self, body):
        req = json.loads(body)
        prot = json.loads(_unb64(req["protected"]))
        jwk = prot.get("jwk") or self.account_jwk
        if prot.get("jwk"):
            self.account_jwk = prot["jwk"]
        pub = ec.EllipticCurvePublicNumbers(
            int.from_bytes(_unb64(jwk["x"]), "big"), int.from_bytes(_unb64(jwk["y"]), "big"), ec.SECP256R1()
        ).public_key()
        sig = _unb64(req["signature"])
        pub.verify(
            encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")),
            f"{req['protected']}.{req['payload']}".encode(),
            ec.ECDSA(hashes.SHA256()),
        )
        assert prot["alg"] == "ES256" and prot["nonce"] == "n1" and prot["url"]
        return prot, (json.loads(_unb64(req["payload"])) if req["payload"] else None)

    def __call__(self, method, url, headers, body):
        h = {"replay-nonce": "n1"}
        if method == "GET" and url == self.D:
            return (
                200,
                json.dumps(
                    {
                        "newNonce": "https://acme.test/nonce",
                        "newAccount": "https://acme.test/acct",
                        "newOrder": "https://acme.test/order",
                    }
                ),
                h,
            )
        if method == "HEAD":
            return 200, "", h
        prot, payload = self._verify(body)
        self.posts.append((url, payload, "kid" in prot))
        if self.bad_nonces:
            self.bad_nonces -= 1
            return 400, json.dumps({"type": "urn:ietf:params:acme:error:badNonce", "detail": "old nonce"}), h
        if url.endswith("/acct"):
            assert payload == {"termsOfServiceAgreed": True}
            return 201, "{}", {**h, "location": "https://acme.test/acct/1"}
        if url.endswith("/order"):
            assert payload["identifiers"] == [{"type": "dns", "value": "home.duckdns.org"}]
            return (
                201,
                json.dumps({"authorizations": ["https://acme.test/authz/1"], "finalize": "https://acme.test/fin"}),
                {**h, "location": "https://acme.test/order/1"},
            )
        if url.endswith("/authz/1"):
            if self.challenged:
                return (
                    200,
                    json.dumps(
                        {
                            "status": "invalid" if self.bad else "valid",
                            "challenges": [{"error": {"detail": "TXT not found"}}] if self.bad else [],
                        }
                    ),
                    h,
                )
            return (
                200,
                json.dumps(
                    {
                        "status": "pending",
                        "challenges": [
                            {"type": "http-01", "token": "x", "url": "u"},
                            {"type": "dns-01", "token": "tok", "url": "https://acme.test/ch/1"},
                        ],
                    }
                ),
                h,
            )
        if url.endswith("/ch/1"):
            self.challenged = True
            return 200, "{}", h
        if url.endswith("/fin"):
            csr = x509.load_der_x509_csr(_unb64(payload["csr"]))
            assert csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(
                x509.DNSName
            ) == ["home.duckdns.org"]
            return 200, json.dumps({"status": "processing"}), h
        if url.endswith("/order/1"):
            return 200, json.dumps({"status": "valid", "certificate": "https://acme.test/cert/1"}), h
        if url.endswith("/cert/1"):
            return 200, self.pem, h
        return 404, "{}", h


def _dns_ok():
    calls = []

    def http(method, url, headers, body):
        calls.append(url)
        return 200, "OK"

    return http, calls


def test_off_by_default_and_needs_dynamic_dns_first():
    st = acme_dns.public_state()
    assert (
        st["enabled"] is False
        and st["has_cert"] is False
        and st["ddns_ready"] is False
        and "letsencrypt" in st["terms"]
    )
    st = acme_dns.issue(now=1.0, http3=FakeAcme(), sleep=lambda s: None)
    assert "Set up Dynamic DNS first" in st["last_error"]


def test_gets_a_certificate_with_a_dns_check_and_removes_the_record(monkeypatch):
    monkeypatch.setattr(acme_dns, "LE", FakeAcme.D)
    ddns.save(True, "duckdns", "home", "duck-token")
    acme_dns.save(True, False)
    fake = FakeAcme()
    http, calls = _dns_ok()
    st = acme_dns.issue(now=100.0, http3=fake, http=http, sleep=lambda s: None)
    assert st["last_error"] == "" and st["has_cert"] is True and st["hostname"] == "home.duckdns.org"
    assert st["not_after"] > 100.0 and acme_dns.days_left() >= 88
    assert "txt=" in calls[0] and "domains=home" in calls[0] and "clear=true" in calls[-1]
    assert all(kid for (_u, _p, kid) in fake.posts[1:])  # after the account, requests carry the kid
    cert, key = acme_dns.cert_paths()
    with open(key, "rb") as f:
        assert serialization.load_pem_private_key(f.read(), None)
    assert acme_dns.renew_due(100.0 + 86401) is False  # 90 days left
    assert acme_dns.renew_due(st["not_after"] - 10 * 86400) is True


def test_a_failed_check_is_said_and_the_record_still_removed(monkeypatch):
    monkeypatch.setattr(acme_dns, "LE_STAGING", FakeAcme.D)
    ddns.save(False, "duckdns", "home", "duck-token")
    acme_dns.save(True, True)
    http, calls = _dns_ok()
    st = acme_dns.issue(now=5.0, http3=FakeAcme(bad_challenge=True), http=http, sleep=lambda s: None)
    assert "could not confirm the name: TXT not found" in st["last_error"] and st["has_cert"] is False
    assert "clear=true" in calls[-1]
    st = acme_dns.issue(now=6.0, http3=lambda *a: (503, "", {}), http=http, sleep=lambda s: None)
    assert "could not be reached" in st["last_error"]


def test_cloudflare_txt_record_is_made_and_deleted():
    ddns.save(False, "cloudflare", "nas.example.com", "cf")
    calls = []

    def http(method, url, headers, body):
        calls.append((method, url, json.loads(body) if body else None))
        if "/zones?per_page" in url:
            return 200, json.dumps({"result": [{"id": "z1", "name": "example.com"}]})
        if method == "POST":
            return 200, json.dumps({"result": {"id": "t1"}})
        return 200, "{}"

    remove = acme_dns.set_txt("nas.example.com", "VALUE", http=http)
    post = [c for c in calls if c[0] == "POST"][0]
    assert post[2] == {"type": "TXT", "name": "_acme-challenge.nas.example.com", "content": "VALUE", "ttl": 60}
    remove()
    assert calls[-1][0] == "DELETE" and calls[-1][1].endswith("/dns_records/t1")
    with pytest.raises(RuntimeError, match="none of the domains"):
        acme_dns.set_txt("nas.other.net", "V", http=http)


def test_routes(client, auth_headers, monkeypatch):
    from backend import tls_server

    monkeypatch.setattr(tls_server, "start", lambda app=None, **kw: False)
    monkeypatch.setattr(tls_server, "stop", lambda wait=10.0: None)
    res = client.get("/api/network/https", headers=auth_headers).json()
    assert res["enabled"] is False and res["port"] == 8443 and res["serving"] is False
    res = client.put("/api/network/https", headers=auth_headers, json={"enabled": True, "staging": True}).json()
    assert res["enabled"] is True and res["staging"] is True
    monkeypatch.setattr(
        acme_dns, "issue", lambda: {**acme_dns.public_state(), "last_error": "Set up Dynamic DNS first."}
    )
    res = client.post("/api/network/https/certificate", headers=auth_headers).json()
    assert "Dynamic DNS" in res["last_error"]
    assert client.put("/api/network/https", headers=auth_headers, json={"enabled": False}).json()["enabled"] is False


def test_the_listener_starts_only_with_https_on_and_a_certificate(tmp_path):
    from backend import tls_server

    assert tls_server.start(object(), enabled=False, cert="c", key="k") is False
    assert (
        tls_server.start(object(), enabled=True, cert=str(tmp_path / "none.pem"), key=str(tmp_path / "none.key"))
        is False
    )
    assert tls_server.serving() is False
    tls_server.stop(wait=0.1)
    assert tls_server.restart(enabled=False) is False


def test_a_refused_nonce_is_tried_again(monkeypatch):
    """Servers turn nonces down now and then (RFC 8555 6.5): one such answer failed the certificate."""
    monkeypatch.setattr(acme_dns, "LE", FakeAcme.D)
    ddns.save(True, "duckdns", "home", "duck-token")
    acme_dns.save(True, False)
    http, _calls = _dns_ok()
    fake = FakeAcme(bad_nonces=2)
    st = acme_dns.issue(now=100.0, http3=fake, http=http, sleep=lambda s: None)
    assert st["last_error"] == "" and st["has_cert"] is True
    assert [u for (u, _p, _k) in fake.posts[:3]] == ["https://acme.test/acct"] * 3
    st = acme_dns.issue(now=200.0, http3=FakeAcme(bad_nonces=3), http=http, sleep=lambda s: None)
    assert st["last_error"] == "Let's Encrypt refused: old nonce"  # not for ever


def test_a_name_proved_lately_is_not_proved_again(monkeypatch):
    """Asked again soon after, the server says the name is valid already and refuses an answer to
    its check: no TXT record, no answer, and the certificate comes."""
    monkeypatch.setattr(acme_dns, "LE", FakeAcme.D)
    ddns.save(True, "duckdns", "home", "duck-token")
    acme_dns.save(True, False)
    http, calls = _dns_ok()
    fake = FakeAcme(proved=True)
    st = acme_dns.issue(now=100.0, http3=fake, http=http, sleep=lambda s: None)
    assert st["last_error"] == "" and st["has_cert"] is True
    assert calls == [] and not any(u.endswith("/ch/1") for (u, _p, _k) in fake.posts)


def test_a_check_already_under_way_is_not_answered_twice(monkeypatch):
    monkeypatch.setattr(acme_dns, "LE", FakeAcme.D)
    ddns.save(True, "duckdns", "home", "duck-token")
    acme_dns.save(True, False)
    http, calls = _dns_ok()
    fake = FakeAcme()
    real = fake.__call__

    def looking(method, url, headers, body):
        status, text, h = real(method, url, headers, body)
        if url.endswith("/authz/1") and not fake.challenged:
            data = json.loads(text)
            data["challenges"][1]["status"] = "processing"
            fake.challenged = True  # the server is looking already
            text = json.dumps(data)
        return status, text, h

    st = acme_dns.issue(now=100.0, http3=looking, http=http, sleep=lambda s: None)
    assert st["last_error"] == "" and "clear=true" in calls[-1]
    assert not any(u.endswith("/ch/1") for (u, _p, _k) in fake.posts)
