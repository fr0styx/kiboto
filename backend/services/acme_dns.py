"""HTTPS at home through ACME over DNS (audit A9, owner decision 16 Nov 2026). Kiboto asks Let's
Encrypt for a certificate for the Dynamic DNS name (backend/services/ddns.py) and proves it owns the
name with a DNS TXT record set through the same provider and token (DuckDNS or Cloudflare): no port
has to be open for this. The certificate is renewed when 30 days are left. Off by default; nothing is
asked of Let's Encrypt until the owner presses "Get a certificate" (which accepts its Subscriber
Agreement, linked on the page).

A small RFC 8555 client on the cryptography package: the account uses an EC P-256 pair and signs
requests with ES256; one dns-01 authorization; the certificate gets its own P-256 pair."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import time
import urllib.parse
from collections.abc import Callable
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.x509.oid import NameOID

from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, read_json
from backend.services import ddns

TLS_DIR = os.path.join(DATA_DIR, "tls")
STATE_FILE = os.path.join(TLS_DIR, "state.json")
LE = "https://acme-v02.api.letsencrypt.org/directory"
LE_STAGING = "https://acme-staging-v02.api.letsencrypt.org/directory"
TERMS = "https://letsencrypt.org/repository/"
RENEW_DAYS = 30
DNS_WAIT_SECS = 45

Http = ddns.Http  # (method, url, headers, body) -> (status, text); headers come back via _last_headers


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _defaults() -> dict[str, Any]:
    return {
        "enabled": False,
        "staging": False,
        "hostname": "",
        "not_after": 0.0,
        "last_try": 0.0,
        "last_error": "",
        "issued_at": 0.0,
    }


def state() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    return {**_defaults(), **(data if isinstance(data, dict) else {})}


def _save(st: dict[str, Any]) -> None:
    os.makedirs(TLS_DIR, mode=0o700, exist_ok=True)
    atomic_write_json(STATE_FILE, st)


def cert_paths() -> tuple[str, str]:
    return os.path.join(TLS_DIR, "cert.pem"), os.path.join(TLS_DIR, "key.pem")


def public_state() -> dict[str, Any]:
    st = state()
    d = ddns.public_state()
    cert, key = cert_paths()
    st.update(
        {
            "ddns_ready": bool(d["hostname"] and d["token_set"]),
            "ddns_hostname": d["hostname"],
            "has_cert": os.path.exists(cert) and os.path.exists(key),
            "terms": TERMS,
        }
    )
    return st


def save(enabled: bool, staging: bool) -> dict[str, Any]:
    st = state()
    st.update({"enabled": bool(enabled), "staging": bool(staging)})
    _save(st)
    return public_state()


class Acme:
    """One ACME session against a directory; http is replaceable for tests."""

    def __init__(
        self, directory: str, key: ec.EllipticCurvePrivateKey, http: Callable[..., tuple[int, str, dict[str, str]]]
    ):
        self.http, self.key, self.kid = http, key, ""
        status, text, _ = http("GET", directory, {}, None)
        if status != 200:
            raise RuntimeError("Let's Encrypt could not be reached.")
        self.dir = json.loads(text)
        self.nonce = ""

    def jwk(self) -> dict[str, str]:
        n = self.key.public_key().public_numbers()
        return {"crv": "P-256", "kty": "EC", "x": _b64(n.x.to_bytes(32, "big")), "y": _b64(n.y.to_bytes(32, "big"))}

    def thumbprint(self) -> str:
        j = self.jwk()
        return _b64(
            hashlib.sha256(
                json.dumps({k: j[k] for k in ("crv", "kty", "x", "y")}, separators=(",", ":")).encode()
            ).digest()
        )

    def _nonce(self) -> str:
        if self.nonce:
            n, self.nonce = self.nonce, ""
            return n
        _s, _t, h = self.http("HEAD", self.dir["newNonce"], {}, None)
        return h.get("replay-nonce", "")

    def post(self, url: str, payload: Any) -> tuple[int, Any, dict[str, str]]:
        protected: dict[str, Any] = {"alg": "ES256", "nonce": self._nonce(), "url": url}
        protected.update({"kid": self.kid} if self.kid else {"jwk": self.jwk()})
        p64 = _b64(json.dumps(protected).encode())
        b64 = "" if payload is None else _b64(json.dumps(payload).encode())
        r, s = decode_dss_signature(self.key.sign(f"{p64}.{b64}".encode(), ec.ECDSA(hashes.SHA256())))
        body = json.dumps(
            {"protected": p64, "payload": b64, "signature": _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))}
        ).encode()
        status, text, headers = self.http("POST", url, {"Content-Type": "application/jose+json"}, body)
        self.nonce = headers.get("replay-nonce", "")
        try:
            data: Any = json.loads(text) if text and text.lstrip().startswith("{") else text
        except ValueError:
            data = text
        if status >= 400:
            detail = data.get("detail") if isinstance(data, dict) else ""
            raise RuntimeError(f"Let's Encrypt refused: {detail or status}")
        return status, data, headers

    def account(self) -> None:
        _s, _d, h = self.post(self.dir["newAccount"], {"termsOfServiceAgreed": True})
        self.kid = h.get("location", "")

    def poll(self, url: str, want: str, tries: int = 20, wait: float = 3.0, sleep=time.sleep) -> dict[str, Any]:
        for _ in range(tries):
            _s, data, _h = self.post(url, None)
            if data.get("status") == want:
                return data
            if data.get("status") == "invalid":
                err = (data.get("error") or {}).get("detail") or next(
                    (c.get("error", {}).get("detail") for c in data.get("challenges", []) if c.get("error")), ""
                )
                raise RuntimeError(f"Let's Encrypt could not confirm the name: {err or 'invalid'}")
            sleep(wait)
        raise RuntimeError("Let's Encrypt did not answer in time.")


def _http3(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, str, dict[str, str]]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": "Kiboto-ACME", **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (Let's Encrypt only)
            return r.status, r.read(1 << 20).decode("utf-8", "replace"), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read(1 << 16).decode("utf-8", "replace"), {k.lower(): v for k, v in e.headers.items()}


def _account_key() -> ec.EllipticCurvePrivateKey:
    path = os.path.join(TLS_DIR, "account.pem")
    if os.path.exists(path):
        with open(path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), None)
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        return key
    key = ec.generate_private_key(ec.SECP256R1())
    os.makedirs(TLS_DIR, mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
    return key


def set_txt(hostname: str, value: str, http: Http = ddns._http) -> Callable[[], Any]:
    """Puts the challenge TXT record through the Dynamic DNS provider; returns how to remove it."""
    raw = ddns._raw()
    token = ddns._token(raw)
    if raw["provider"] == "duckdns":
        sub = hostname[: -len(".duckdns.org")]
        q = urllib.parse.urlencode({"domains": sub, "token": token, "txt": value, "verbose": "true"})
        status, text = http("GET", f"https://www.duckdns.org/update?{q}", {}, None)
        if status != 200 or not text.startswith("OK"):
            raise RuntimeError("DuckDNS refused the TXT record.")
        clear = urllib.parse.urlencode({"domains": sub, "token": token, "txt": "", "clear": "true"})
        return lambda: http("GET", f"https://www.duckdns.org/update?{clear}", {}, None)
    auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    status, text = http("GET", ddns.CF_API + "/zones?per_page=50", auth, None)
    zones = (json.loads(text or "{}").get("result") or []) if status == 200 else []
    zone = max(
        (z for z in zones if hostname == z.get("name") or hostname.endswith("." + str(z.get("name")))),
        key=lambda z: len(str(z.get("name"))),
        default=None,
    )
    if not zone:
        raise RuntimeError("Cloudflare: none of the domains this token can see holds that name.")
    body = json.dumps({"type": "TXT", "name": f"_acme-challenge.{hostname}", "content": value, "ttl": 60}).encode()
    status, text = http("POST", f"{ddns.CF_API}/zones/{zone['id']}/dns_records", auth, body)
    if status >= 300:
        raise RuntimeError("Cloudflare refused the TXT record. The token needs DNS: Edit.")
    rid = (json.loads(text or "{}").get("result") or {}).get("id", "")
    return lambda: http("DELETE", f"{ddns.CF_API}/zones/{zone['id']}/dns_records/{rid}", auth, None)


def issue(now: float | None = None, http3=_http3, http: Http = ddns._http, sleep=time.sleep) -> dict[str, Any]:
    """Gets (or renews) the certificate for the Dynamic DNS name. Records the outcome; never raises."""
    now = time.time() if now is None else now
    st = state()
    st["last_try"] = now
    hostname = ddns._raw().get("hostname", "")
    remove: Callable[[], Any] | None = None
    try:
        if not (hostname and ddns.public_state()["token_set"]):
            raise RuntimeError("Set up Dynamic DNS first: the certificate is for that name.")
        acme = Acme(LE_STAGING if st["staging"] else LE, _account_key(), http3)
        acme.account()
        _s, order, h = acme.post(acme.dir["newOrder"], {"identifiers": [{"type": "dns", "value": hostname}]})
        order_url = h.get("location", "")
        _s, authz, _h = acme.post(order["authorizations"][0], None)
        ch = next((c for c in authz["challenges"] if c["type"] == "dns-01"), None)
        if ch is None:
            raise RuntimeError("Let's Encrypt offered no DNS check for this name.")
        txt = _b64(hashlib.sha256(f"{ch['token']}.{acme.thumbprint()}".encode()).digest())
        remove = set_txt(hostname, txt, http=http)
        sleep(DNS_WAIT_SECS)  # time for the TXT record to reach the name servers
        acme.post(ch["url"], {})
        acme.poll(order["authorizations"][0], "valid", sleep=sleep)
        cert_key = ec.generate_private_key(ec.SECP256R1())
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
            .sign(cert_key, hashes.SHA256())
        )
        acme.post(order["finalize"], {"csr": _b64(csr.public_bytes(serialization.Encoding.DER))})
        done = acme.poll(order_url, "valid", sleep=sleep)
        _s, pem, _h = acme.post(done["certificate"], None)
        if not isinstance(pem, str) or "BEGIN CERTIFICATE" not in pem:
            raise RuntimeError("Let's Encrypt sent no certificate.")
        cert = x509.load_pem_x509_certificate(pem.encode())
        cert_path, key_path = cert_paths()
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(
                cert_key.private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
                )
            )
        with open(cert_path, "w", encoding="ascii") as f:
            f.write(pem)
        st.update(
            {
                "hostname": hostname,
                "not_after": cert.not_valid_after_utc.timestamp(),
                "issued_at": now,
                "last_error": "",
            }
        )
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        st["last_error"] = str(e) if isinstance(e, RuntimeError) else "The certificate could not be obtained."
    finally:
        if remove:
            try:
                remove()
            except (OSError, RuntimeError):
                pass
    _save(st)
    return public_state()


def renew_due(now: float) -> bool:
    st = state()
    if not st["enabled"] or now - float(st["last_try"] or 0) < 86400:
        return False
    return float(st["not_after"] or 0) - now < RENEW_DAYS * 86400


def days_left(now: float | None = None) -> int:
    na = float(state()["not_after"] or 0)
    return int((na - (time.time() if now is None else now)) // 86400) if na else 0


def utc(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%d")
