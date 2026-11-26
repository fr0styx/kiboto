"""Three ways a release could look checked while it was not (found by the release review of 25 Nov
2026): the update test passing with every older version skipped, Stable taking an image signed
only for the main branch, and a tag's digest file gone before its approval came."""

import os
import shutil
import subprocess

import pytest
import yaml

from backend import legacy_names

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _wf(name):
    with open(os.path.join(ROOT, ".github", "workflows", name), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _step(job, prefix):
    return next(s for s in job["steps"] if str(s.get("name", "")).startswith(prefix))


def _update_test() -> str:
    return _step(_wf("ci.yml")["jobs"]["update-test"], "Upgrade and rollback test")["run"]


def test_the_update_test_starts_from_the_image_name_since_the_rebrand():
    run = _update_test()
    new = run.index('OLD="${{ env.IMAGE }}:$tag${{ matrix.suffix }}"')
    old = run.index('OLD="${{ env.OLD_IMAGE }}:$tag${{ matrix.suffix }}"')
    assert new < old  # the old name only for a version from before the rebrand (it stops at 2.2)


def test_the_update_test_fails_when_fewer_than_two_older_versions_were_tried():
    run = _update_test()
    assert "passed=$((passed + 1))" in run
    assert 'if [ "$passed" -lt 2 ]; then' in run
    tail = run[run.index('if [ "$passed" -lt 2 ]; then') :]
    assert "exit 1" in tail.split("fi")[0]


def _result(outcomes):
    """The step's own counting, run with pretend outcomes (0 passed, 77 skipped, else failed)."""
    run = _update_test()
    body = run[run.index('failed=""') :]
    started = " ".join(f"{i}:{i}:t{i}" for i in range(1, len(outcomes) + 1))
    codes = " ".join(str(c) for c in outcomes)
    script = (
        f'started="{started}"\ncodes="{codes}"\n'
        'wait() { set -- $codes; n=$1; shift; codes="$*"; return $n; }\n'
        "cat() { :; }\n" + body
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)  # noqa: S603,S607


@pytest.mark.skipif(not shutil.which("bash"), reason="no bash")
@pytest.mark.parametrize(
    "outcomes, ok",
    [
        ([0, 0, 0], True),
        ([0, 77, 0], True),  # one version not published: two still tried
        ([0, 77, 77], False),  # green before this change, with one base tested
        ([77, 77, 77], False),  # and with none
        ([0, 0, 1], False),
    ],
)
def test_the_counting_itself(outcomes, ok):
    done = _result(outcomes)
    assert (done.returncode == 0) is ok, done.stdout + done.stderr


def test_a_tags_digest_file_outlives_a_late_approval():
    build = _wf("ci.yml")["jobs"]["build-image"]
    upload = next(s for s in build["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact"))
    assert upload["with"]["name"] == "digest-${{ matrix.variant }}"
    assert upload["with"]["retention-days"] >= 30


def _promote_check() -> str:
    return _step(_wf("promote.yml")["jobs"]["promote"], "Verify and retag")["run"]


def test_stable_takes_only_the_signature_made_for_that_version_tag():
    run = _promote_check()
    assert "heads/main" not in run
    assert "@refs/tags/v${VERSION//./\\\\.}\\$" in run


@pytest.mark.skipif(not shutil.which("bash"), reason="no bash")
@pytest.mark.parametrize(
    "identity, ok",
    [
        ("https://github.com/fr0styx/kiboto/.github/workflows/ci.yml@refs/tags/v2.0.7", True),
        (f"https://github.com/{legacy_names.OLD_IMAGE_REPO}/.github/workflows/ci.yml@refs/tags/v2.0.7", True),
        ("https://github.com/fr0styx/kiboto/.github/workflows/ci.yml@refs/heads/main", False),
        ("https://github.com/fr0styx/kiboto/.github/workflows/ci.yml@refs/tags/v2.0.70", False),
        ("https://github.com/fr0styx/kiboto/.github/workflows/ci.yml@refs/tags/v2.0.6", False),
        ("https://github.com/fr0styx/kiboto/.github/workflows/ci.yml@refs/tags/v2x0x7", False),
        ("https://github.com/someone/kiboto/.github/workflows/ci.yml@refs/tags/v2.0.7", False),
    ],
)
def test_the_pattern_as_the_workflow_writes_it(identity, ok):
    run = _promote_check()
    line = next(x for x in run.splitlines() if "--certificate-identity-regexp" in x)
    pattern_expr = line.split("--certificate-identity-regexp", 1)[1].strip().rstrip("\\").strip()
    script = f'VERSION=2.0.7\nre={pattern_expr}\nprintf "%s" "$1" | grep -Eq "$re"'
    done = subprocess.run(["bash", "-c", script, "x", identity], capture_output=True, text=True, check=False)  # noqa: S603,S607
    assert (done.returncode == 0) is ok, (identity, done.stderr)


# ── Kiboto OS checks every update's signature, whatever UPDATE_SIGNATURES says ──


def test_a_machine_that_takes_only_releases_always_enforces(monkeypatch):
    from backend import config
    from backend.services import image_signature as sig

    monkeypatch.setattr(sig, "releases_only", lambda: True)
    for mode in ("enforce", "warn", "off"):
        monkeypatch.setattr(config, "UPDATE_SIGNATURES", mode)
        assert sig.signature_mode() == "enforce"
    monkeypatch.setattr(sig, "releases_only", lambda: False)  # a container, or a test machine
    for mode in ("enforce", "warn", "off"):
        monkeypatch.setattr(config, "UPDATE_SIGNATURES", mode)
        assert sig.signature_mode() == mode


def test_the_root_service_checks_the_signature_there_even_with_warn_set(monkeypatch):
    from backend import config
    from backend.services import docker_client
    from backend.services import image_signature as sig

    good = "sha256:" + "b" * 64
    monkeypatch.setattr(
        docker_client, "request", lambda *a, **k: (200, {"RepoDigests": [f"ghcr.io/fr0styx/kiboto@{good}"]})
    )
    monkeypatch.setattr(config, "UPDATE_SIGNATURES", "warn")
    monkeypatch.setattr(sig, "releases_only", lambda: True)
    asked = []
    monkeypatch.setattr(
        sig, "verify_image", lambda d, tags: asked.append((d, tags)) or sig.SignatureResult(False, "no sig")
    )
    with pytest.raises(ValueError, match="no sig"):
        sig.install_allowed("ghcr.io/fr0styx/kiboto:2.0.7")
    assert asked == [(good, True)]


def test_the_update_route_there_neither_skips_the_check_nor_suggests_warn(client, auth_headers, monkeypatch):
    from backend import config
    from backend.api import system
    from backend.services import image_signature as sig

    digest = "sha256:" + "d" * 64

    async def _registry(tag):
        return digest

    monkeypatch.setattr(system, "_registry_digest", _registry)
    monkeypatch.setattr("backend.services.container_mutator.pull_container_image", lambda *a, **k: None)
    monkeypatch.setattr(system, "_local_repo_digests", lambda ref: [digest])
    monkeypatch.setattr(system, "docker_sock", lambda: "/nonexistent.sock")
    monkeypatch.setattr(config, "UPDATE_SIGNATURES", "off")
    monkeypatch.setattr(sig, "releases_only", lambda: True)
    asked = []
    monkeypatch.setattr(
        sig,
        "verify_image",
        lambda d, tags_only=False: asked.append(tags_only) or sig.SignatureResult(False, "the image has no signature"),
    )
    r = client.post("/api/system/updates/apply", json={"channel": "stable"}, headers=auth_headers)
    assert asked == [True]  # "off" did not skip it
    assert r.status_code == 502 and "no signature" in r.json()["detail"]
    assert "UPDATE_SIGNATURES" not in r.json()["detail"]
    # where the setting can let it through, the page still says so
    monkeypatch.setattr(sig, "releases_only", lambda: False)
    monkeypatch.setattr(config, "UPDATE_SIGNATURES", "enforce")
    r = client.post("/api/system/updates/apply", json={"channel": "stable"}, headers=auth_headers)
    assert r.status_code == 502 and "UPDATE_SIGNATURES=warn" in r.json()["detail"]
