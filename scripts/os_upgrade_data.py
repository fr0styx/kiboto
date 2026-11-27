"""Data made on one release must still be there after an update (scripts/os_install_check.sh).

Runs inside the test machine, as root, against Kiboto's own API, as a person would use it:

    python3 os_upgrade_data.py make D1 D2   # earlier release: sign in, a ZFS mirror, a shared folder, a file
    python3 os_upgrade_data.py after D3     # this build: a new pool and a shared folder on it, at once
    python3 os_upgrade_data.py look         # every pool, shared folder and file still there

The first sign-in uses the code the installer wrote into /root/install.log; the administrator then gets
a random password kept only in /root/upgrade-admin (0600). Nothing secret is printed.
"""

import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "http://127.0.0.1:8082"
SECRET = "/root/upgrade-admin"
PROOF = "/root/upgrade-proof"
failed = 0


def call(method, path, body=None, token="", extra=None, timeout=300):
    head = {"Content-Type": "application/json", "Origin": API, **(extra or {})}
    if token:
        head["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, headers=head, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def confirmed(method, path, body, token):
    """A step the server asks to confirm first (428), confirmed as the page does."""
    code, out = call(method, path, body, token)
    if code == 428:
        ticket = call("POST", "/api/confirmations", out, token)[1].get("token", "")
        code, out = call(method, path, body, token, {"X-Confirm-Token": ticket})
    return code, out


def sign_in(password):
    code, out = call("POST", "/api/auth/login", {"username": "admin", "password": password})
    return code, out.get("access_token") or out.get("token") or ""


def say(ok, what, detail=""):
    global failed
    if not ok:
        failed += 1
    print(
        f"  {'ok    ' if ok else 'FAILED'}  {what}" + (f": {str(detail)[:200]}" if detail and not ok else ""),
        flush=True,
    )


def healthy():
    for _ in range(60):
        if call("GET", "/api/health", timeout=5)[0] == 200:
            return True
        time.sleep(3)
    return False


def proofs():
    try:
        with open(PROOF, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def pool_and_share(token, password, pool, share, disks, profile, restart_once=False):
    """A pool through the page's API, a shared folder on it and a file in that folder."""
    body = {
        "name": pool,
        "fs_type": "zfs",
        "profile": profile,
        "disks": disks,
        "confirm_name": pool,
        "current_password": password,
        "erase_existing_data": True,
    }
    code, out = confirmed("POST", "/api/storage/pools", body, token)
    say(code in (200, 201, 202), f"a ZFS pool {pool} on {' and '.join(disks)}", out)
    mount = ""
    for _ in range(60):  # a pool is made in the background on some machines
        rows = call("GET", "/api/storage/pools", token=token)[1].get("pools", [])
        row = next((p for p in rows if p.get("name") == pool), None)
        if row and row.get("mountpoint"):
            mount = row["mountpoint"]
            break
        time.sleep(3)
    say(bool(mount), f"Kiboto says where {pool} is", mount)
    folder = os.path.join(mount or "/nonexistent", share)
    body = {"name": share, "path": folder, "comment": "update check"}
    code, out = confirmed("POST", "/api/storage/shares", body, token)
    if restart_once and code == 400 and "system disk" in str(out):
        # Kiboto 2.0.8 and older left the pool record root's until the next start: a known fault of
        # those releases (fixed after them), worked around here so the update itself can be checked
        print(f"  note    the earlier release needed a restart before {share} could go on its new pool", flush=True)
        subprocess.run(["systemctl", "restart", "kiboto-door", "kiboto"], check=False, timeout=180)
        healthy()
        code, token = sign_in(password)
        code, out = confirmed("POST", "/api/storage/shares", body, token)
    say(code in (200, 201), f"a shared folder {share} on {pool}", out)
    text = secrets.token_hex(16)
    try:
        with open(os.path.join(folder, "update-proof.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        say(True, f"a file in {share}")
    except OSError as e:
        say(False, f"a file in {share}", e)
    kept = proofs()
    kept[share] = {"pool": pool, "folder": folder, "text": text}
    with open(PROOF, "w", encoding="utf-8") as f:
        json.dump(kept, f)
    return token


def make(disks):
    with open("/root/install.log", encoding="utf-8", errors="replace") as f:
        codes = re.findall(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}\b", f.read())
    if not codes:
        say(False, "the first sign-in code is in the install log")
        return
    code, token = sign_in(codes[-1])
    say(code == 200 and bool(token), "the administrator signs in with the first sign-in code", code)
    me = call("GET", "/api/auth/me", token=token)[1]
    uid = me.get("id") or (me.get("user") or {}).get("id")
    password = "Kb-" + secrets.token_urlsafe(18)
    body = {"current_password": codes[-1], "new_password": password}
    code, _ = call("POST", f"/api/users/{uid}/password", body, token)
    say(code == 200, "the administrator chooses a password", code)
    fd = os.open(SECRET, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(password)
    code, token = sign_in(password)
    say(code == 200, "and signs in with it", code)
    pool_and_share(token, password, "tank", "family", disks, "mirror", restart_once=True)


def after(disks):
    """On this build, without any restart: a new pool must take a shared folder at once."""
    with open(SECRET, encoding="utf-8") as f:
        password = f.read().strip()
    code, token = sign_in(password)
    say(code == 200, "the administrator signs in on this build", code)
    pool_and_share(token, password, "fresh", "photos", disks, "single")


def look():
    with open(SECRET, encoding="utf-8") as f:
        code, token = sign_in(f.read().strip())
    say(code == 200, "the administrator still signs in with the password chosen before", code)
    pools = call("GET", "/api/storage/pools", token=token)[1].get("pools", [])
    shares = call("GET", "/api/storage/shares", token=token)[1].get("shares", [])
    conf = subprocess.run(["testparm", "-s"], capture_output=True, text=True, timeout=60).stdout
    for share, proof in proofs().items():
        pool = next((p for p in pools if p.get("name") == proof["pool"]), None)
        state = " ".join(str(pool.get(k) or "") for k in ("health", "status", "state")).lower() if pool else ""
        say(
            bool(pool) and ("online" in state or "healthy" in state),
            f"the pool {proof['pool']} is there and healthy",
            state or [p.get("name") for p in pools],
        )
        say(
            any(s.get("name") == share for s in shares),
            f"Kiboto lists the shared folder {share}",
            [s.get("name") for s in shares],
        )
        say(f"[{share}]" in conf, f"Samba shares {share}")
        try:
            with open(os.path.join(proof["folder"], "update-proof.txt"), encoding="utf-8") as f:
                have = f.read()
        except OSError as e:
            have = f"unreadable: {e}"
        say(have == proof["text"], f"the file in {share} is unchanged", have[:40])


if __name__ == "__main__":
    if sys.argv[1:2] == ["make"]:
        make(sys.argv[2:])
    elif sys.argv[1:2] == ["after"]:
        after(sys.argv[2:])
    elif sys.argv[1:2] == ["look"]:
        look()
    else:
        sys.exit(__doc__)
    sys.exit(1 if failed else 0)
