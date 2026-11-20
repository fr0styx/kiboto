"""Data tiering over the API: for whoever manages the storage, turning a folder on and moving its
files now are confirmed, and each change is logged."""

import pytest

from backend.services import tiering as tr

VIEW = {"folders": [], "run_at": "03:00"}


@pytest.fixture(autouse=True)
def service(monkeypatch):
    calls = []
    state = {"on": None, "calls": calls, "refuse": None}

    def set_folder(name, enabled, days=90, now=None, slow=""):
        if state["refuse"]:
            raise tr.NotNow(state["refuse"], "Refused.", value=3650)
        calls.append(("set", name, enabled, days, slow) if slow else ("set", name, enabled, days))
        state["on"] = {"name": name} if enabled else None

    def run_soon(name, how="hand"):
        if state["refuse"]:
            raise tr.NotNow(state["refuse"], "Refused.")
        calls.append(("run", name))

    monkeypatch.setattr(tr, "view", lambda now=None: VIEW)
    monkeypatch.setattr(tr, "candidates", lambda: state.get("fits", [{"name": "Films", "why": ""}]))
    monkeypatch.setattr(tr, "get", lambda name: state["on"])
    monkeypatch.setattr(tr, "set_folder", set_folder)
    monkeypatch.setattr(tr, "run_soon", run_soon)
    monkeypatch.setattr(tr, "watch", lambda now=None: calls.append(("watch",)))
    return state


def test_only_someone_who_manages_the_storage_reaches_it(client, monkeypatch):
    monkeypatch.setattr(
        "backend.auth.get_current_session",
        lambda tok: {
            "user_id": "u_sam",
            "username": "sam",
            "role_id": "viewer",
            "scopes": ["system:view", "shares:manage"],
        },
    )
    h = {"Authorization": "Bearer x"}
    for method, path, body in [
        ("get", "/api/tiering", None),
        ("put", "/api/tiering/folders/Films", {"enabled": True}),
        ("post", "/api/tiering/folders/Films/run", None),
    ]:
        assert client.request(method, path, json=body, headers=h).status_code == 403, (method, path)


def test_a_folder_is_turned_on_changed_run_and_turned_off(client, auth_headers, service, monkeypatch):
    logged = []
    monkeypatch.setattr(
        "backend.users_db.log_security_event", lambda event, *a, **k: logged.append((event, k.get("details")))
    )
    assert client.get("/api/tiering", headers=auth_headers).json() == VIEW
    res = client.put("/api/tiering/folders/Films", json={"enabled": True, "days": 30}, headers=auth_headers)
    assert res.status_code == 200 and res.json() == VIEW
    assert client.put("/api/tiering/folders/Films", json={"enabled": True}, headers=auth_headers).status_code == 200
    assert client.post("/api/tiering/folders/Films/run", headers=auth_headers).status_code == 200
    assert client.put("/api/tiering/folders/Films", json={"enabled": False}, headers=auth_headers).status_code == 200
    assert service["calls"] == [
        ("set", "Films", True, 30),
        ("watch",),
        ("set", "Films", True, 90),
        ("watch",),
        ("run", "Films"),
        ("set", "Films", False, 90),
        ("watch",),
    ]
    own = [(e, d) for e, d in logged if not e.startswith("confirm.")]
    assert own[0] == ("tiering.set", {"folder": "Films", "enabled": True, "days": 30})
    assert own[2] == ("tiering.run", {"folder": "Films"})
    assert own[3] == ("tiering.set", {"folder": "Films", "enabled": False, "days": None})
    # turning it on was confirmed once (changing the days of a folder that is on is not), and so was the run
    assert [e for e, _ in logged if e.startswith("confirm.")] == ["confirm.tiering.enable", "confirm.tiering.run"]


@pytest.mark.real_confirmations
def test_turning_a_folder_on_and_moving_now_ask_first(client, auth_headers, service):
    res = client.put("/api/tiering/folders/Films", json={"enabled": True}, headers=auth_headers)
    assert res.status_code == 428 and service["calls"] == []
    assert client.post("/api/tiering/folders/Films/run", headers=auth_headers).status_code == 428
    # turning it off never asks
    assert client.put("/api/tiering/folders/Films", json={"enabled": False}, headers=auth_headers).status_code == 200
    for action in ("tiering.enable", "tiering.run"):
        made = client.post("/api/confirmations", json={"action": action, "target": "Films"}, headers=auth_headers)
        assert made.status_code == 200, made.text
        assert "Films" in made.json()["summary"]


@pytest.mark.parametrize(
    "key,status",
    [("no_fit", 400), ("bad_days", 400), ("no_folder", 404), ("busy", 409), ("no_slow", 400), ("merge_failed", 409)],
)
def test_a_refusal_says_which_one_in_the_readers_language(client, auth_headers, service, key, status):
    service["refuse"] = key
    res = client.put("/api/tiering/folders/Films", json={"enabled": True}, headers=auth_headers)
    assert res.status_code == status and res.json()["error"] == f"tiering_{key}"
    assert res.json()["text"]["msg_key"] == f"srv.tiering_{key}"
    assert client.post("/api/tiering/folders/Films/run", headers=auth_headers).status_code == status


def test_making_a_folder_a_merged_one_is_confirmed_in_its_own_words(client, auth_headers, service, monkeypatch):
    logged = []
    monkeypatch.setattr("backend.users_db.log_security_event", lambda event, *a, **k: logged.append(event))
    service["fits"] = [{"name": "Films", "why": "", "kind": "merged", "slow_pool": "", "slow_choices": []}]
    body = {"enabled": True, "days": 30, "slow": "p-hdd"}
    assert client.put("/api/tiering/folders/Films", json=body, headers=auth_headers).status_code == 200
    assert service["calls"][0] == ("set", "Films", True, 30, "p-hdd")
    assert [e for e in logged if e.startswith("confirm.")] == ["confirm.tiering.merge"]
    # merged already (tiering was off for it): turning it on again is the ordinary question
    service["on"], service["fits"][0]["slow_pool"] = None, "p-hdd"
    assert client.put("/api/tiering/folders/Films", json={"enabled": True}, headers=auth_headers).status_code == 200
    assert [e for e in logged if e.startswith("confirm.")][-1] == "confirm.tiering.enable"
