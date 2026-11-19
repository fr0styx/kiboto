"""Catalog apps that must know the address people reach them at (re-audit, 19 Nov 2026)."""

from backend.services import app_catalog

APP = {
    "id": "wiki",
    "name": "Wiki",
    "image": "example/wiki:1",
    "default_port": 6875,
    "env": {"APP_URL": "http://{{host}}:{{port}}", "KEY": "{{secret:app_key}}", "TZ": "UTC"},
    "volumes": {},
    "stack_services": {
        "db": {"image": "mariadb:lts", "env": {"MYSQL_USER": "wiki"}},
        "web": {"image": "example/web:1", "env": {"ROOT_URL": "http://{{host}}:{{port}}/x"}},
        "cache": {"image": "redis:7"},
    },
}


def test_settings_that_use_the_address_are_filled_and_nothing_else_changes():
    assert app_catalog.needs_address(APP) is True
    out = app_catalog.with_address(APP, "nas.local", 7000)
    assert out["env"] == {"APP_URL": "http://nas.local:7000", "KEY": "{{secret:app_key}}", "TZ": "UTC"}
    assert out["stack_services"]["web"]["env"] == {"ROOT_URL": "http://nas.local:7000/x"}
    assert out["stack_services"]["db"]["env"] == {"MYSQL_USER": "wiki"}
    assert out["stack_services"]["cache"] == {"image": "redis:7"}
    assert APP["env"]["APP_URL"] == "http://{{host}}:{{port}}"  # the template itself is untouched
    plain = {"env": {"TZ": "UTC"}}
    assert app_catalog.needs_address(plain) is False and app_catalog.needs_address({}) is False
    assert app_catalog.with_address(plain, "x", 1) == {"env": {"TZ": "UTC"}}
    only_companion = {"env": {}, "stack_services": {"web": {"env": {"U": "{{host}}"}}}}
    assert app_catalog.needs_address(only_companion) is True


def test_an_install_without_a_known_address_is_refused_before_anything_is_made(monkeypatch):
    monkeypatch.setattr(app_catalog, "get_catalog_app", lambda _id: dict(APP))
    for host in ("", "not a host!", "a b"):
        events = list(app_catalog.stream_deploy_catalog_app("wiki", browser_host=host))
        assert len(events) == 1 and events[0]["step"] == "error" and events[0]["done"] is True
        assert events[0]["message"].startswith("Wiki must know the address people open it at.")
        assert events[0]["text"] == {
            "msg_key": "install.needs_address",
            "params": {"app": "Wiki"},
        }  # translated by the page


def test_with_an_address_the_install_goes_on_with_the_filled_settings(monkeypatch):
    seen = {}
    monkeypatch.setattr(app_catalog, "get_catalog_app", lambda _id: dict(APP))

    def stop(app, share_folders):
        seen["env"] = dict(app["env"])
        return {}, "stopped here on purpose"

    monkeypatch.setattr(app_catalog, "share_folder_paths", stop)
    events = list(app_catalog.stream_deploy_catalog_app("wiki", host_port=7000, browser_host="192.168.1.9"))
    assert events[0]["step"] == "init" and events[-1]["message"] == "stopped here on purpose"
    assert seen["env"]["APP_URL"] == "http://192.168.1.9:7000"
    # the default port when none was chosen; an app that needs no address is passed through; an unknown one is None
    assert app_catalog.app_for_install("wiki", "nas.local")["env"]["APP_URL"] == "http://nas.local:6875"
    monkeypatch.setattr(app_catalog, "get_catalog_app", lambda _id: {"id": "plain", "env": {"TZ": "UTC"}})
    assert app_catalog.app_for_install("plain") == {"id": "plain", "env": {"TZ": "UTC"}}
    monkeypatch.setattr(app_catalog, "get_catalog_app", lambda _id: None)
    assert app_catalog.app_for_install("nope") is None


def test_every_builtin_app_that_needs_an_address_says_so_in_the_catalog():
    """The install dialog only works from a browser for these; none may sneak in unnoticed."""
    from backend.services.catalog_templates import CURATED_APP_CATALOG

    bound = sorted(a["id"] for a in CURATED_APP_CATALOG if app_catalog.needs_address(a))
    assert bound == sorted(a["id"] for a in CURATED_APP_CATALOG if a.get("address_bound"))
