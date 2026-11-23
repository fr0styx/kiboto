"""The image takes Debian's security fixes at least once a day: the package layers are keyed by the
day CI builds on, not only by the build cache (which kept a Chromium Debian had fixed)."""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_the_first_package_layer_uses_the_day():
    docker = _read("Dockerfile")
    first_apt = docker.index("apt-get update")
    assert docker.index('ARG APT_DAY=""') < first_apt
    assert "${APT_DAY" in docker[docker.rfind("RUN", 0, first_apt) : first_apt]


def test_ci_passes_todays_date():
    ci = _read(".github", "workflows", "ci.yml")
    assert 'echo "day=$(date -u +%F)" >> "$GITHUB_OUTPUT"' in ci
    assert "APT_DAY=${{ steps.day.outputs.day }}" in ci
