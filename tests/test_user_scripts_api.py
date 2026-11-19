"""Scheduled scripts over the API: the full administrator only, confirmed where it matters, logged."""

import time

import pytest

from backend.services import user_scripts as us


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(us, "STATE_FILE", str(tmp_path / "scripts.json"))
    monkeypatch.setattr(us, "RUNS_FILE", str(tmp_path / "runs.json"))
    monkeypatch.setattr(us, "WORK_DIR", str(tmp_path))
    share = tmp_path / "share"
    share.mkdir()
    monkeypatch.setattr(us, "ALLOWED_BROWSE_ROOTS", [str(share)])
    monkeypatch.setattr(us, "limit_available", lambda now=None: True)
    us.reset_for_tests()
    yield share
    for sid in list(us.running()):
        us.stop(sid)
    us.reset_for_tests()


BODY = {"name": "Tidy up", "body": "echo hello", "schedule": {"kind": "daily", "at": "03:30"}}


def _other(monkeypatch, scopes):
    monkeypatch.setattr(
        "backend.auth.get_current_session",
        lambda tok: {"user_id": "u_sam", "username": "sam", "role_id": "storage_admin", "scopes": scopes},
    )
    return {"Authorization": "Bearer x"}


def test_only_the_full_administrator_reaches_any_of_it(client, monkeypatch):
    h = _other(monkeypatch, ["system:config", "storage:admin", "shares:manage", "system:view"])
    for method, path, body in [
        ("get", "/api/scripts", None),
        ("put", "/api/scripts/enabled", {"enabled": True}),
        ("post", "/api/scripts", BODY),
        ("put", "/api/scripts/abc", BODY),
        ("delete", "/api/scripts/abc", None),
        ("post", "/api/scripts/abc/run", None),
        ("post", "/api/scripts/abc/stop", None),
        ("get", "/api/scripts/abc/runs", None),
    ]:
        res = client.request(method, path, json=body, headers=h)
        assert res.status_code == 403, (method, path, res.status_code)
    assert client.get("/api/scripts").status_code in (401, 403)
    assert us.enabled() is False and us.scripts() == []


def test_the_whole_life_of_a_script(client, auth_headers, fresh, monkeypatch):
    logged = []
    from backend import users_db

    monkeypatch.setattr(
        users_db, "log_security_event", lambda event, status, **k: logged.append((event, k.get("details")))
    )
    view = client.get("/api/scripts", headers=auth_headers).json()
    assert view == {"enabled": False, "can_limit": True, "max_scripts": 20, "max_timeout_min": 720, "scripts": []}

    made = client.post("/api/scripts", json={**BODY, "limit_folder": str(fresh)}, headers=auth_headers).json()
    one = made["scripts"][0]
    assert one["name"] == "Tidy up" and one["limit_folder"] == str(fresh) and one["timeout_min"] == 30
    assert one["next_run"] > time.time() and one["last_run"] is None and one["running"] is None
    sid = one["id"]

    off = client.post(f"/api/scripts/{sid}/run", headers=auth_headers)
    assert off.status_code == 409 and off.json()["error"] == "script_off"
    assert client.put("/api/scripts/enabled", json={"enabled": True}, headers=auth_headers).json()["enabled"] is True

    changed = client.put(
        f"/api/scripts/{sid}", json={**BODY, "body": "echo changed", "limit_folder": ""}, headers=auth_headers
    )
    assert changed.status_code == 200 and changed.json()["scripts"][0]["body"] == "echo changed"
    assert client.post(f"/api/scripts/{sid}/run", headers=auth_headers).json()["status"] == "started"
    end = time.time() + 20
    while time.time() < end and not us.last_run(sid):
        time.sleep(0.05)
    runs = client.get(f"/api/scripts/{sid}/runs", headers=auth_headers).json()
    assert runs["running"] is None and runs["runs"][0]["output"] == "changed\n" and runs["runs"][0]["how"] == "by_hand"
    listed = client.get("/api/scripts", headers=auth_headers).json()["scripts"][0]["last_run"]
    assert listed["ok"] is True and "output" not in listed  # the list stays small; the output is asked for

    assert client.post(f"/api/scripts/{sid}/stop", headers=auth_headers).json() == {"stopped": False}
    assert client.delete(f"/api/scripts/{sid}", headers=auth_headers).json()["scripts"] == []
    for method, path in [
        ("delete", f"/api/scripts/{sid}"),
        ("post", f"/api/scripts/{sid}/run"),
        ("get", f"/api/scripts/{sid}/runs"),
    ]:
        gone = client.request(method, path, headers=auth_headers)
        assert gone.status_code == 404 and gone.json()["error"] == "script_not_found"
    assert client.put(f"/api/scripts/{sid}", json=BODY, headers=auth_headers).status_code == 404
    assert client.post(f"/api/scripts/{sid}/stop", headers=auth_headers).status_code == 404
    confirmed = [e for e, _ in logged if e.startswith("confirm.")]
    # each save and the switch were confirmed (the last save was for a script that was gone by then)
    assert confirmed == [
        "confirm.scripts.save",
        "confirm.scripts.enable",
        "confirm.scripts.save",
        "confirm.scripts.save",
    ]
    own = [(e, d) for e, d in logged if not e.startswith("confirm.")]
    assert [e for e, _ in own] == ["scripts.save", "scripts.switch", "scripts.save", "scripts.run", "scripts.delete"]
    assert own[0][1] == {"script": "Tidy up", "new": True, "limited_to": str(fresh)}


def test_what_is_wrong_is_said_in_the_readers_language(client, auth_headers):
    bad = client.post("/api/scripts", json={**BODY, "name": "x" * 80}, headers=auth_headers)
    body = bad.json()
    assert bad.status_code == 400 and body["error"] == "script_bad_name"
    assert body["text"] == {"msg_key": "srv.script_bad_name", "params": {"value": us.MAX_NAME}}
    late = client.post("/api/scripts", json={**BODY, "timeout_min": 100000}, headers=auth_headers).json()
    assert late["text"]["params"] == {"value": us.MAX_TIMEOUT_MIN}
    assert (
        client.post(
            "/api/scripts", json={**BODY, "schedule": {"kind": "weekly", "at": "03:30"}}, headers=auth_headers
        ).json()["error"]
        == "script_no_days"
    )


@pytest.mark.real_confirmations
def test_turning_it_on_and_saving_a_script_are_confirmed(client, auth_headers):
    on = client.put("/api/scripts/enabled", json={"enabled": True}, headers=auth_headers)
    assert on.status_code == 428 and on.json()["action"] == "scripts.enable" and us.enabled() is False
    save = client.post("/api/scripts", json=BODY, headers=auth_headers)
    assert save.status_code == 428 and save.json()["action"] == "scripts.save" and us.scripts() == []

    def token(action, target=""):
        return client.post(
            "/api/confirmations", json={"action": action, "target": target}, headers=auth_headers
        ).json()["token"]

    yes = {**auth_headers, "X-Confirm-Token": token("scripts.enable")}
    assert client.put("/api/scripts/enabled", json={"enabled": True}, headers=yes).json()["enabled"] is True
    assert (
        client.put("/api/scripts/enabled", json={"enabled": True}, headers=auth_headers).status_code == 200
    )  # already on
    yes = {**auth_headers, "X-Confirm-Token": token("scripts.save")}
    assert len(client.post("/api/scripts", json=BODY, headers=yes).json()["scripts"]) == 1
    assert client.post("/api/scripts", json=BODY, headers=yes).status_code == 428  # a token works once
    # turning it off never asks
    assert client.put("/api/scripts/enabled", json={"enabled": False}, headers=auth_headers).json()["enabled"] is False


def test_the_sentences_are_there_in_every_language():
    import json
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for lang in ("en", "de", "es", "fr", "zh"):
        text = (root / "frontend" / "src" / "locales" / f"{lang}.js").read_text(encoding="utf-8")
        keys = set(re.findall(r'^  "([^"]+)":', text, flags=re.M))
        for key in ("bad_name", "empty", "too_long", "bad_timeout", "bad_schedule", "bad_time", "no_days", "bad_folder",
                    "too_many", "off", "running", "busy", "no_limit", "not_found", "bad"):  # fmt: skip
            assert f"srv.script_{key}" in keys, (lang, key)
        for why in ("code", "timeout", "limit"):
            assert f"ev.script_failed_{why}.title" in keys and f"ev.script_failed_{why}.msg" in keys, (lang, why)
        for action in ("scripts_enable", "scripts_save"):
            assert f"confirm.{action}.title" in keys and f"confirm.{action}.msg" in keys, (lang, action)
        sent = json.loads((root / "backend" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        assert "ev.script_failed_code.msg" in sent, lang  # the server's own copy, for alerts it words itself
