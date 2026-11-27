"""People, their own folders and shared folders on a Kiboto OS machine, used as people use them
(scripts/os_install_check.sh, after an update in the test machine).

Runs inside the test machine, as root, against Kiboto's own API and its file servers:

    python3 os_people_trials.py

The administrator signs in with the password os_upgrade_data.py kept in /root/upgrade-admin. Three
people are made with generated passwords (never printed); each check says ok or FAILED, as there.
Each check is one that failed on Kiboto OS before (27 Nov): a person's own folder shut to Kiboto, files
saved over the network unreadable to the page, NFS-only shares that took no writes, a storage limit
that held only in the page, a deleted private file nobody could see in the Recycle Bin.
"""

import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8082"
failed = 0


def say(ok, what, detail=""):
    global failed
    if not ok:
        failed += 1
    print(
        f"  {'ok    ' if ok else 'FAILED'}  {what}" + (f": {str(detail)[:200]}" if detail and not ok else ""),
        flush=True,
    )


def sh(cmd, timeout=120):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


def call(method, path, body=None, token="", extra=None, raw=None):
    head = {"Origin": API, **(extra or {})}
    if token:
        head["Authorization"] = "Bearer " + token
    if raw is not None:
        data, head["Content-Type"] = raw, "application/octet-stream"
    else:
        data, head["Content-Type"] = (json.dumps(body).encode() if body is not None else None), "application/json"
    req = urllib.request.Request(API + path, data=data, headers=head, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
            try:
                return r.status, json.loads(body or b"{}")
            except ValueError:
                return r.status, body
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def confirmed(method, path, body, token):
    code, out = call(method, path, body, token)
    if code == 428:
        ticket = call("POST", "/api/confirmations", out, token)[1].get("token", "")
        code, out = call(method, path, body, token, {"X-Confirm-Token": ticket})
    return code, out


def sign_in(user, password):
    out = call("POST", "/api/auth/login", {"username": user, "password": password})[1]
    return out.get("access_token") or out.get("token") or ""


def smb(share, user, password, commands):
    auth = f"/root/{user}.smb"
    fd = os.open(auth, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"username = {user}\npassword = {password}\n")
    try:
        return sh(f"cd /tmp && smbclient //127.0.0.1/{share} -A {auth} -c '{commands}' 2>&1")
    finally:
        os.remove(auth)


def main():
    with open(os.environ.get("KB_ADMIN_FILE", "/root/upgrade-admin"), encoding="utf-8") as f:
        admin = sign_in("admin", f.read().strip())
    say(bool(admin), "the administrator signs in")
    # what an earlier run left (the test machine at home; the CI machine is new each time)
    for share in ("school", "media"):
        confirmed("DELETE", f"/api/storage/shares/{share}", None, admin)
    for u in call("GET", "/api/users", token=admin)[1].get("users", []):
        if u.get("username") in ("alma", "bodo", "cora"):
            confirmed("DELETE", f"/api/users/{u['id']}", None, admin)
    sh(
        "rm -rf /mnt/storage/*/homes/alma* /mnt/storage/*/homes/bodo* /mnt/storage/*/homes/cora* /mnt/storage/*/school /mnt/storage/*/media"
    )
    if not sh("command -v smbclient"):
        sh("DEBIAN_FRONTEND=noninteractive apt-get install -y -q smbclient", timeout=600)
    people = {}
    for name, quota in (("alma", 0), ("bodo", 0), ("cora", 1024 * 1024)):
        pw = "Kb-" + secrets.token_urlsafe(18)
        code, made = confirmed(
            "POST",
            "/api/users",
            {"username": name, "password": pw, "role_id": "share_user", "storage_quota_bytes": quota},
            admin,
        )
        people[name] = {"pw": pw, "id": (made.get("user") or {}).get("id")}
        say(code == 200, f"{name} is made", code)
    time.sleep(5)
    for name, p in people.items():
        p["tok"] = sign_in(name, p["pw"])
    homes = sh("ls -d /mnt/storage/*/homes | head -1")
    home = f"{homes}/alma"

    # a person's own folder, from the page and over the network
    code, ls = confirmed("GET", f"/api/browse?path={home}", None, people["alma"]["tok"])
    say(code == 200, "alma opens her own folder in Kiboto", code)
    code, _ = call(
        "POST", f"/api/fs/upload?path={home}&filename=diary.txt", token=people["alma"]["tok"], raw=b"dear diary\n"
    )
    owner = sh(f"stat -c '%U %a' {home}/diary.txt")
    say(code == 200 and owner == "alma 660", "a file she uploads in the page is hers", f"{code} {owner}")
    Path("/tmp/letter.txt").write_text("saved over the network\n")
    put = smb("alma", "alma", people["alma"]["pw"], "put /tmp/letter.txt letter.txt")
    say("putting file" in put, "she saves a file in her folder over SMB", put[-120:])
    code, got = call("GET", f"/api/fs/download?path={home}/letter.txt", token=people["alma"]["tok"])
    say(
        code == 200 and b"saved over the network" in (got if isinstance(got, bytes) else b""),
        "and opens it in the page",
        code,
    )
    code, _ = confirmed("GET", f"/api/browse?path={home}", None, people["bodo"]["tok"])
    say(code == 403, "bodo cannot open alma's folder", code)
    say(
        sh(f"sudo -u bodo cat {home}/letter.txt >/dev/null 2>&1 && echo yes || echo no") == "no",
        "nor read her files on the machine",
    )

    # a shared folder: alma may write, bodo may only read
    pool = os.path.dirname(homes)
    code, _ = confirmed(
        "POST",
        "/api/storage/shares",
        {
            "name": "school",
            "path": f"{pool}/school",
            "security": "private",
            "user_permissions": {"alma": "rw", "bodo": "ro"},
        },
        admin,
    )
    say(code == 200, "a shared folder with per-person rights is made", code)
    time.sleep(5)
    say(
        "putting file" in smb("school", "alma", people["alma"]["pw"], "put /tmp/letter.txt homework.txt"),
        "alma writes in it over SMB",
    )
    say(
        "getting file" in smb("school", "bodo", people["bodo"]["pw"], "get homework.txt /tmp/bodo-got.txt"),
        "bodo reads it",
    )
    say(
        "ACCESS_DENIED" in smb("school", "bodo", people["bodo"]["pw"], "put /tmp/letter.txt bodo.txt"),
        "bodo cannot write in it",
    )
    code, _ = call(
        "POST", f"/api/fs/upload?path={pool}/school&filename=page.txt", token=people["bodo"]["tok"], raw=b"x"
    )
    say(code == 403, "nor in the page", code)

    # a shared folder exported over NFS only
    code, _ = confirmed(
        "POST",
        "/api/storage/shares",
        {"name": "media", "path": f"{pool}/media", "security": "private", "export_smb": False, "export_nfs": True},
        admin,
    )
    say(code == 200, "a shared folder exported over NFS only is made", code)
    time.sleep(5)
    me = sh("hostname -I | cut -d' ' -f1")
    sh("mkdir -p /mnt/nfs-check")
    mounted = sh(f"mount -t nfs -o soft,timeo=50 {me}:{pool}/media /mnt/nfs-check 2>&1 && echo mounted")
    wrote = sh("echo hi > /mnt/nfs-check/from-nfs.txt 2>&1 && echo wrote")
    say(mounted.endswith("mounted") and wrote.endswith("wrote"), "a client mounts it and writes", f"{mounted} {wrote}")
    sh("umount -f /mnt/nfs-check")

    # a storage limit, over the network too
    put = smb("cora", "cora", people["cora"]["pw"], "put /tmp/letter.txt small.txt")
    Path("/tmp/big.bin").write_bytes(os.urandom(2 * 1024 * 1024))
    smb("cora", "cora", people["cora"]["pw"], "put /tmp/big.bin big.bin")
    sh("zpool sync; sleep 3")
    again = smb("cora", "cora", people["cora"]["pw"], "put /tmp/big.bin big2.bin")
    say("DISK_FULL" in again or "QUOTA" in again.upper(), "cora's 1 MB limit holds over SMB", again[-120:])

    # the Recycle Bin keeps a deleted private file for its owner only
    code, _ = confirmed("POST", "/api/fs/delete", {"path": f"{home}/diary.txt"}, people["alma"]["tok"])
    seen = {
        n: [
            i.get("id")
            for i in call("GET", "/api/fs/trash", token=p["tok"])[1].get("items", [])
            if i.get("name") == "diary.txt"
        ]
        for n, p in people.items()
        if n != "cora"
    }
    say(
        code == 200 and seen["alma"] and not seen["bodo"],
        "alma sees her deleted file in the Recycle Bin, bodo does not",
        seen,
    )
    if seen["alma"]:
        code, _ = call("POST", "/api/fs/trash/restore", {"item_id": seen["alma"][0]}, people["alma"]["tok"])
        owner = sh(f"stat -c '%U %a' {home}/diary.txt")
        say(code == 200 and owner == "alma 660", "she restores it, and it is hers again", f"{code} {owner}")


if __name__ == "__main__":
    main()
    sys.exit(1 if failed else 0)
