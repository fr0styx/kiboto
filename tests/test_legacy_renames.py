"""Names stored before the rebrand are renamed once where they are stored (backend/legacy_names.py);
the rest of the code knows only Kiboto's names."""

import json

from backend import legacy_names
from backend.fsutil import atomic_write_json
from backend.services import app_after_start


def test_saved_app_definitions_take_kibotos_names(tmp_path):
    old = {
        "apps": [
            {
                "id": "wiki",
                "join_zettnas_network": True,
                "env": {"API": "http://{{zettnas}}:8082/api", "N": 3},
                "after_start": [{"url": "http://{{host}}:{{port}}/setup", "body": ["{{zettnas}}"]}],
            }
        ]
    }
    (tmp_path / "sideloaded_apps.json").write_text(json.dumps(old))
    (tmp_path / "catalog_cache").mkdir()
    (tmp_path / "catalog_cache" / "community.json").write_text(json.dumps(old))
    (tmp_path / "catalog_cache" / "fresh.json").write_text(
        json.dumps({"apps": [{"id": "x", "join_kiboto_network": True}]})
    )
    assert legacy_names.rename_app_files(str(tmp_path), atomic_write_json) == 2
    for name in ("sideloaded_apps.json", "catalog_cache/community.json"):
        text = (tmp_path / name).read_text()
        assert "zettnas" not in text
        app = json.loads(text)["apps"][0]
        assert app["join_kiboto_network"] is True and app["env"] == {"API": "http://{{kiboto}}:8082/api", "N": 3}
        assert app["after_start"][0]["body"] == ["{{kiboto}}"]
    assert legacy_names.rename_app_files(str(tmp_path), atomic_write_json) == 0  # once done, nothing to do
    assert legacy_names.rename_app_files(str(tmp_path / "missing"), atomic_write_json) == 0


def test_the_placeholders_are_kibotos_only():
    ctx = app_after_start.context("nas.local", 8082)
    assert set(ctx) == {"host", "port", "kiboto", "arch"}


def test_rename_at_start_reads_the_data_folder(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(legacy_names, "rename_app_files", lambda d, w: seen.append(d) or 0)
    legacy_names.rename_at_start(str(tmp_path), atomic_write_json)
    assert seen == [str(tmp_path)]


def test_a_broken_file_is_left(tmp_path):
    good = tmp_path / "sideloaded_apps.json"
    good.write_text('{"apps": [{"env": "{{zettnas}}"}]}')
    (tmp_path / "catalog_cache").mkdir()
    (tmp_path / "catalog_cache" / "broken.json").write_text("{not json")
    assert legacy_names.rename_app_files(str(tmp_path), atomic_write_json) == 1
    assert "{{kiboto}}" in good.read_text()
    assert (tmp_path / "catalog_cache" / "broken.json").read_text() == "{not json"


def test_kibotos_own_containers_from_before_are_recognised():
    assert legacy_names.made_before("/zettnas-toolkit") and legacy_names.made_before("zettnas-samba")
    assert not legacy_names.made_before("kiboto") and not legacy_names.made_before(None)
