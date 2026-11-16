"""AI decision 10 (owner, 16 Nov 2026): Kib's settings are for administrators only, one right on every route.

Before, three sets of rights guarded the one page (system:config, storage:admin, and ai:manage that no
built-in role held), so a storage administrator could change some settings and not others. Now every
settings route asks for ai:manage alone; the administrator holds it through "*".
"""

import json
from pathlib import Path

import pytest

from backend.auth import KIB_MANAGE

SETTINGS = {
    ("post", "/api/v1/ai/config"),
    ("put", "/api/v1/ai/config"),
    ("post", "/api/v1/ai/benchmark"),
    ("post", "/api/v1/ai/reindex"),
    ("get", "/api/v1/ai/folders"),
    ("post", "/api/v1/ai/folders"),
    ("post", "/api/v1/ai/index"),
    ("post", "/api/v1/ai/index/sync"),
    ("post", "/api/v1/ai/index/control"),
    ("post", "/api/v1/ai/index/flush"),
    ("post", "/api/v1/ai/index/forget"),
    ("post", "/api/v1/ai/learning/relearn-failed"),
    ("get", "/api/v1/ai/learning/results"),
    ("get", "/api/v1/ai/models/benchmark"),
    ("post", "/api/v1/ai/models/benchmark"),
    ("post", "/api/v1/ai/models/benchmark/apply"),
    ("post", "/api/v1/ai/models/huggingface/pull"),
    ("get", "/api/v1/ai/models/huggingface/search"),
    ("post", "/api/v1/ai/models/install"),
    ("get", "/api/v1/ai/models/install/{job_id}"),
    ("post", "/api/v1/ai/models/install/{job_id}/cancel"),
    ("get", "/api/v1/ai/models/installed"),
    ("get", "/api/v1/ai/models/recommendations"),
    ("post", "/api/v1/ai/models/remove"),
    ("delete", "/api/v1/ai/models/remove"),
    ("post", "/api/v1/ai/models/select"),
    ("get", "/api/v1/ai/access"),
    ("put", "/api/v1/ai/access"),
    ("get", "/api/v1/ai/requests"),
    ("get", "/api/v1/ai/apps"),
    ("post", "/api/v1/ai/apps/keys"),
    ("delete", "/api/v1/ai/apps/keys/{token_id}"),
    ("get", "/api/v1/ai/pack"),
    ("post", "/api/v1/ai/pack/install"),
    ("post", "/api/v1/ai/pack/use"),
}

ROLES = {
    "storage_admin": ["storage:*", "shares:*", "system:view", "hardware:read", "logs:read", "audit:read"],
    "config_only": ["system:config", "system:read", "storage:read", "shares:read"],
    "kib_admin": [KIB_MANAGE],
}


def _scopes(op):
    for key in ("x-required-scopes", "x-scopes"):
        if key in op:
            return op[key]
    return next((v for k, v in op.items() if k.startswith("x-") and isinstance(v, list)), [])


def test_every_kib_settings_route_asks_for_the_one_right():
    doc = json.loads(Path("docs/openapi-v1.json").read_text())
    wrong = {}
    for meth, path in sorted(SETTINGS):
        op = doc["paths"][path][meth]
        if _scopes(op) != [KIB_MANAGE]:
            wrong[f"{meth.upper()} {path}"] = _scopes(op)
    assert not wrong, wrong


def test_using_kib_still_needs_no_settings_right():
    doc = json.loads(Path("docs/openapi-v1.json").read_text())
    for path in ("/api/v1/ai/chat", "/api/v1/ai/search", "/api/v1/ai/conversations"):
        assert KIB_MANAGE not in _scopes(doc["paths"][path]["post"]), path
    assert KIB_MANAGE not in _scopes(doc["paths"]["/api/v1/ai/config"]["get"])


@pytest.fixture
def as_role(monkeypatch):
    def use(role):
        monkeypatch.setattr(
            "backend.auth.get_current_session",
            lambda tok: {"user_id": f"u_{role}", "username": role, "role_id": role, "scopes": ROLES[role]},
        )
        return {"Authorization": "Bearer x"}

    return use


@pytest.mark.parametrize("role", ["storage_admin", "config_only"])
@pytest.mark.parametrize(
    "meth,path,body",
    [
        ("put", "/api/ai/config", {"enabled": True}),
        ("post", "/api/ai/reindex", {}),
        ("post", "/api/ai/index", {"path": "/mnt/user/x"}),
        ("get", "/api/ai/folders", None),
        ("get", "/api/ai/learning/results", None),
        ("put", "/api/ai/access", {}),
        ("get", "/api/ai/pack", None),
    ],
)
def test_other_rights_no_longer_open_kib_settings(client, as_role, role, meth, path, body):
    kw = {"json": body} if body is not None else {}
    assert getattr(client, meth)(path, headers=as_role(role), **kw).status_code == 403


def test_the_one_right_opens_them(client, as_role):
    assert client.get("/api/ai/folders", headers=as_role("kib_admin")).status_code != 403
