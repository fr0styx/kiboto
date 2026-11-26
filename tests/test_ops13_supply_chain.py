"""Signatures are accepted only from the release workflow; logs are capped (OPS-13)."""

import os
import re

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_promotion_verifies_the_ci_workflow_identity():
    """Promotion verifies who signed: Kiboto's own CI workflow, for the version tag being promoted.
    tests/test_release_traps.py tries the pattern itself against right and wrong identities."""
    text = _read(".github/workflows/promote.yml")
    line = next(x for x in text.splitlines() if "--certificate-identity-regexp" in x)
    assert "/\\\\.github/workflows/ci\\\\.yml@refs/tags/v${VERSION" in line
    assert "heads/main" not in text  # a main-branch signature does not make an image a release
    assert "--certificate-oidc-issuer https://token.actions.githubusercontent.com" in text


def test_linux_compose_caps_container_logs():
    services = yaml.safe_load(_read("docker-compose.linux.yml"))["services"]
    for name in ("zettnas-toolkit", "zettnas-samba"):
        opts = services[name]["logging"]["options"]
        assert opts["max-size"] and opts["max-file"], name


def test_images_get_tags_only_after_the_gates():
    # The image is built and checked in its own jobs while the tests run; the tags are added in
    # the publish job, which needs every check (CI speed-up, 12 Nov 2026)
    jobs = yaml.safe_load(_read(".github/workflows/ci.yml"))["jobs"]
    build = next(s for s in jobs["build-arch"]["steps"] if s.get("id") == "build")
    assert "push-by-digest=true" in build["with"]["outputs"] and "tags" not in build["with"]
    # the join pushes the two architectures' index by its digest; its tag is never pushed
    join = next(s for s in jobs["build-image"]["steps"] if s.get("id") == "build")["run"]
    assert "imagetools create --dry-run" in join and "/manifests/$digest" in join
    names = [s.get("name", "") for s in jobs["publish"]["steps"]]
    publish = next(i for i, n in enumerate(names) if n.startswith("Publish tags"))
    assert next(i for i, n in enumerate(names) if n.startswith("Sign image digest")) < publish
    for gate, job in (
        ("Smoke-test", "check-image"),
        ("Smoke-test", "smoke-arm64"),
        ("Scan image with Trivy", "check-image"),
    ):
        assert any(s.get("name", "").startswith(gate) for s in jobs[job]["steps"]), (gate, job)
        assert job in jobs["publish"]["needs"], job


def test_arm64_images_are_started_in_ci():
    jobs = yaml.safe_load(_read(".github/workflows/ci.yml"))["jobs"]
    step = next(
        s for s in jobs["smoke-arm64"]["steps"] if s.get("name", "").startswith("Smoke-test the built image (arm64")
    )
    assert "smoke-arm64" in jobs["publish"]["needs"]
    assert "scripts/smoke_test.sh" in step["run"] and "linux/arm64" in step["run"]
    with open(os.path.join(ROOT, "scripts", "smoke_test.sh"), encoding="utf-8") as f:
        script = f.read()
    assert "--platform" in script and "aarch64" in script


def test_the_update_path_is_exercised_before_publishing():
    jobs = yaml.safe_load(_read(".github/workflows/ci.yml"))["jobs"]
    steps = jobs["update-test"]["steps"]
    names = [s.get("name", "") for s in steps]
    test = names.index("Upgrade and rollback test")
    assert "update-test" in jobs["publish"]["needs"]  # runs before any tag is published
    assert "scripts/upgrade_rollback_test.sh" in steps[test]["run"]
    assert os.path.isfile(os.path.join(ROOT, "scripts", "upgrade_rollback_test.sh"))
