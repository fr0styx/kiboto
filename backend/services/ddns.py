"""Dynamic DNS (audit A8, owner decision 16 Nov 2026): keeps a name such as home.duckdns.org or
nas.example.com pointing at this home's public IP, so Kiboto has a stable outside name without
Tailscale or NetBird. Off by default; DuckDNS or Cloudflare; the token is sealed at rest and never
sent back to the page. Every 5 minutes while on: DuckDNS is asked to update (it sees the IP itself);
for Cloudflare the IP comes from Cloudflare's own address check and the record changes only when the
IP did. Nothing leaves the NAS while it is off."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, read_json

STATE_FILE = os.path.join(DATA_DIR, "ddns.json")
EVERY_SECS = 300
PROVIDERS = ("duckdns", "cloudflare")
CF_API = "https://api.cloudflare.com/client/v4"
TIMEOUT = 15

# (method, url, headers, body) -> (status, text); replaced in tests
Http = Callable[[str, str, dict[str, str], bytes | None], tuple[int, str]]


def _http(method: str, url: str, headers: dict[str, str], body: bytes | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": "Kiboto-DDNS", **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 (fixed https providers only)
            return r.status, r.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(65536).decode("utf-8", "replace")


def _defaults() -> dict[str, Any]:
    return {
        "enabled": False,
        "provider": "duckdns",
        "hostname": "",
        "token": "",
        "last_ip": "",
        "last_run": 0.0,
        "last_ok": 0.0,
        "last_error": "",
    }


def _raw() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    return {**_defaults(), **(data if isinstance(data, dict) else {})}


def public_state() -> dict[str, Any]:
    """What the page may see: everything but the token, which is only said to be set."""
    st = _raw()
    out = {k: v for k, v in st.items() if k != "token"}
    out["token_set"] = bool(st.get("token"))
    out["providers"] = list(PROVIDERS)
    return out


def normalize_hostname(provider: str, hostname: str) -> str:
    h = (hostname or "").strip().lower().rstrip(".")
    if provider == "duckdns" and h and "." not in h:
        h += ".duckdns.org"
    return h


def valid_hostname(provider: str, hostname: str) -> bool:
    labels = hostname.split(".")
    if len(labels) < 2 or len(hostname) > 253:
        return False
    if provider == "duckdns" and not hostname.endswith(".duckdns.org"):
        return False
    return all(
        1 <= len(lb) <= 63 and lb.replace("-", "").isalnum() and not lb.startswith("-") and not lb.endswith("-")
        for lb in labels
    )


def save(enabled: bool, provider: str, hostname: str, token: str | None) -> dict[str, Any]:
    """Saves the settings. token None keeps the stored one; "" clears it. Raises ValueError with a
    sentence for the page when the settings can't work."""
    from backend.errors import SaidError
    from backend.secret_box import seal

    if provider not in PROVIDERS:
        raise SaidError("Choose DuckDNS or Cloudflare.", "ddns_provider")
    hostname = normalize_hostname(provider, hostname)
    st = _raw()
    if hostname and not valid_hostname(provider, hostname):
        raise SaidError(
            "That name can't be used. Use letters, digits and hyphens, like home.duckdns.org or nas.example.com.",
            "ddns_name",
        )
    if token is not None:
        st["token"] = seal(token.strip()) if token.strip() else ""
    if enabled and not (hostname and st.get("token")):
        raise SaidError("Fill in the name and the token before turning it on.", "ddns_fill_in")
    changed = provider != st.get("provider") or hostname != st.get("hostname")
    st.update({"enabled": bool(enabled), "provider": provider, "hostname": hostname})
    if changed:
        st.update({"last_ip": "", "last_ok": 0.0, "last_error": ""})
    atomic_write_json(STATE_FILE, st)
    return public_state()


def _token(st: dict[str, Any]) -> str:
    from backend.secret_box import unseal

    return unseal(st.get("token") or "")


def _duckdns(hostname: str, token: str, http: Http) -> str:
    sub = hostname[: -len(".duckdns.org")]
    q = urllib.parse.urlencode({"domains": sub, "token": token, "verbose": "true"})
    status, text = http("GET", f"https://www.duckdns.org/update?{q}", {}, None)
    lines = text.strip().splitlines()
    if status != 200 or not lines or lines[0].strip() != "OK":
        raise RuntimeError("DuckDNS refused the update. Check the name and the token.")
    return lines[1].strip() if len(lines) > 1 else ""


def _cf_ip(http: Http) -> str:
    status, text = http("GET", "https://1.1.1.1/cdn-cgi/trace", {}, None)
    for line in text.splitlines():
        if line.startswith("ip="):
            return line[3:].strip()
    raise RuntimeError("Could not learn this home's public address from Cloudflare.")


def _cf(hostname: str, token: str, last_ip: str, http: Http) -> str:
    ip = _cf_ip(http)
    if ip == last_ip:
        return ip
    auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def call(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        status, text = http(method, CF_API + path, auth, json.dumps(body).encode() if body is not None else None)
        try:
            data = json.loads(text or "{}")
        except ValueError:
            data = {}
        if status in (401, 403):
            raise RuntimeError("Cloudflare refused the token. It needs Zone: Read and DNS: Edit for this domain.")
        if status >= 300 or not data.get("success", False):
            raise RuntimeError(f"Cloudflare answered {status}. Check the name and the token.")
        return data

    zones = call("GET", "/zones?per_page=50").get("result") or []
    zone = max(
        (z for z in zones if hostname == z.get("name") or hostname.endswith("." + str(z.get("name")))),
        key=lambda z: len(str(z.get("name"))),
        default=None,
    )
    if not zone:
        raise RuntimeError("None of the domains this token can see holds that name.")
    zid = zone["id"]
    q = urllib.parse.urlencode({"type": "A", "name": hostname})
    records = call("GET", f"/zones/{zid}/dns_records?{q}").get("result") or []
    if records:
        call("PATCH", f"/zones/{zid}/dns_records/{records[0]['id']}", {"content": ip})
    else:
        call(
            "POST",
            f"/zones/{zid}/dns_records",
            {"type": "A", "name": hostname, "content": ip, "ttl": 300, "proxied": False},
        )
    return ip


def run_once(now: float | None = None, http: Http = _http) -> dict[str, Any]:
    """One update, recorded. Runs even when off (the page's "Update now" after saving)."""
    now = time.time() if now is None else now
    st = _raw()
    st["last_run"] = now
    try:
        if not (st["hostname"] and st.get("token")):
            raise RuntimeError("Fill in the name and the token first.")
        token = _token(st)
        if st["provider"] == "duckdns":
            ip = _duckdns(st["hostname"], token, http)
        else:
            ip = _cf(st["hostname"], token, st.get("last_ip", ""), http)
        st.update({"last_ip": ip or st.get("last_ip", ""), "last_ok": now, "last_error": ""})
    except (RuntimeError, OSError, ValueError) as e:
        st["last_error"] = str(e) if isinstance(e, RuntimeError) else "The provider could not be reached."
    atomic_write_json(STATE_FILE, st)
    return public_state()


def due(now: float) -> bool:
    st = _raw()
    return bool(st["enabled"]) and now - float(st["last_run"] or 0) >= EVERY_SECS
