"""The app's cards read the feature table: what GitHub and the website say, the app says."""

import json

from backend import runtime
from backend.services import edition_features as ef


def test_every_feature_the_app_reads_has_a_state_on_each_column():
    with open(ef.FILE, encoding="utf-8") as f:
        table = json.load(f)["features"]
    assert {"drive_replace", "merged_folders", "iscsi", "move_to_os"} <= set(table)
    states = {"yes", "partly", "view", "host", "soon", "check", "no"}
    for name, cols in table.items():
        assert set(cols) == {"beside", "linux", "os"} and set(cols.values()) <= states, name


def test_the_column_follows_where_kiboto_runs(monkeypatch):
    class Platform:
        def __init__(self, value):
            self.value = value

        def get_platform_type(self):
            return type("T", (), {"value": self.value})()

    from backend.hardware import pal_storage

    monkeypatch.setattr(runtime, "managed_host", lambda: True)
    assert ef.column() == "os"
    monkeypatch.setattr(runtime, "managed_host", lambda: False)
    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: Platform("generic_linux"))
    assert ef.column() == "linux"
    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: Platform("unraid"))
    assert ef.column() == "beside"

    def broken():
        raise RuntimeError("no platform")

    monkeypatch.setattr(pal_storage, "get_storage_platform", broken)
    assert ef.column() == "linux"


def test_state_and_here_read_this_editions_column(monkeypatch):
    monkeypatch.setattr(ef, "column", lambda: "os")
    assert ef.state("move_to_os") == "check" and ef.state("move_to_os", "beside") == "no"
    assert ef.state("nothing such") == ""
    assert ef.here()["iscsi"] == "yes"


def test_a_missing_table_says_nothing(monkeypatch, tmp_path):
    ef._table.cache_clear()
    monkeypatch.setattr(ef, "FILE", str(tmp_path / "none.json"))
    try:
        assert ef.state("iscsi", "os") == "" and ef.here() == {}
    finally:
        ef._table.cache_clear()
