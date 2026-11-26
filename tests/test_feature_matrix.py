"""The feature matrix (docs/feature-matrix.json) and the two pages written from it stay in step.

docs/FEATURES.md is what GitHub shows and docs/features.html is what the website shows. Both are
written by scripts/feature_matrix.py, so a change to the source without `write` fails here.
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import feature_matrix  # noqa: E402


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_the_source_is_complete():
    assert feature_matrix.problems(feature_matrix.load()) == []


def test_both_pages_are_written_from_the_source():
    assert feature_matrix.behind() == [], (
        "the feature pages are behind docs/feature-matrix.json: python scripts/feature_matrix.py write"
    )


def test_every_feature_is_on_both_pages():
    matrix = feature_matrix.load()
    markdown, page = _read("docs/FEATURES.md"), _read("docs/features.html")
    for group in matrix["groups"]:
        for feature in group["features"]:
            assert feature["name"] in markdown
            assert feature_matrix.html.escape(feature["name"]) in page


def test_the_three_ways_to_run_kiboto_are_the_columns():
    assert [c["id"] for c in feature_matrix.load()["columns"]] == ["beside", "linux", "os"]


def test_the_readme_and_the_os_guide_point_to_the_list():
    assert "docs/FEATURES.md" in _read("README.md")
    assert "FEATURES.md" in _read("docs/KIBOTO_OS.md")


def test_the_page_runs_no_script():
    # The website's content policy allows no inline script; the page must not need one.
    assert "<script" not in _read("docs/features.html")


def _matrix():
    return {
        "columns": [{"id": c, "name": c, "short": c, "about": c} for c in ("beside", "linux", "os")],
        "states": {"yes": "Yes", "no": "No"},
        "groups": [{"name": "Storage", "features": [{"name": "Pools", "beside": "yes", "linux": "no", "os": "yes"}]}],
    }


def test_a_missing_edition_is_a_problem():
    matrix = _matrix()
    del matrix["groups"][0]["features"][0]["os"]
    assert feature_matrix.problems(matrix) == ["Pools: nothing for os"]


def test_an_unknown_word_is_a_problem():
    matrix = _matrix()
    matrix["groups"][0]["features"][0]["os"] = "maybe"
    assert "is not one of" in feature_matrix.problems(matrix)[0]


def test_a_name_used_twice_is_a_problem():
    matrix = _matrix()
    matrix["groups"][0]["features"].append(dict(matrix["groups"][0]["features"][0]))
    assert "used twice" in feature_matrix.problems(matrix)[0]


def test_two_columns_are_a_problem():
    matrix = _matrix()
    matrix["columns"].pop()
    assert "there must be three columns" in feature_matrix.problems(matrix)


def test_a_note_is_shown_under_the_name_and_escaped():
    matrix = _matrix()
    matrix["groups"][0]["features"][0]["note"] = "Not in <core>."
    assert "<br><sub>Not in <core>.</sub>" in feature_matrix.markdown(matrix)
    assert "<small>Not in &lt;core&gt;.</small>" in feature_matrix.page(matrix)


@pytest.fixture
def elsewhere(tmp_path, monkeypatch):
    source = tmp_path / "feature-matrix.json"
    source.write_text(json.dumps(_matrix()), encoding="utf-8")
    monkeypatch.setattr(feature_matrix, "SOURCE", str(source))
    monkeypatch.setattr(feature_matrix, "MARKDOWN", str(tmp_path / "FEATURES.md"))
    monkeypatch.setattr(feature_matrix, "PAGE", str(tmp_path / "features.html"))
    monkeypatch.setattr(feature_matrix, "APP", str(tmp_path / "edition_features.json"))
    monkeypatch.setattr(feature_matrix, "ROOT", str(tmp_path))
    return tmp_path


def test_check_fails_until_write_has_run(elsewhere, capsys):
    assert feature_matrix.main(["x", "check"]) == 1
    assert "FEATURES.md" in capsys.readouterr().out
    assert feature_matrix.main(["x", "write"]) == 0
    assert feature_matrix.main(["x", "check"]) == 0


def test_check_fails_when_the_source_changes_after_write(elsewhere):
    feature_matrix.main(["x", "write"])
    matrix = _matrix()
    matrix["groups"][0]["features"][0]["linux"] = "yes"
    (elsewhere / "feature-matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
    assert feature_matrix.main(["x", "check"]) == 1


def test_a_broken_source_is_refused(elsewhere, capsys):
    matrix = _matrix()
    matrix["groups"][0]["features"][0]["os"] = ""
    (elsewhere / "feature-matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
    assert feature_matrix.main(["x", "write"]) == 1
    assert "nothing for os" in capsys.readouterr().err
    assert not (elsewhere / "FEATURES.md").exists()


def test_no_command_prints_the_help(elsewhere, capsys):
    assert feature_matrix.main(["x"]) == 2
    assert "feature_matrix.py write" in capsys.readouterr().out
