"""A release carries SHA256SUMS for install.sh and the install image, signed keyless (Sigstore)."""

from pathlib import Path

import yaml

CI = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def _job():
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]["create-release"]


def test_the_release_job_may_sign():
    assert _job()["permissions"].get("id-token") == "write"


def test_checksums_are_made_signed_and_attached_before_the_release():
    steps = _job()["steps"]
    names = [s.get("name", "") for s in steps]
    sums = names.index("Checksums of what the release carries")
    sign = names.index("Sign the checksums")
    create = names.index("Create Release")
    assert names.index("Build the install image") < sums < sign < create
    assert "sha256sum $files > SHA256SUMS" in steps[sums]["run"]
    assert "cosign sign-blob --yes --bundle SHA256SUMS.sigstore.json SHA256SUMS" in steps[sign]["run"]
    files = steps[create]["with"]["files"].split()
    assert files == ["install.sh", "SHA256SUMS", "SHA256SUMS.sigstore.json"]


def test_the_guide_says_how_to_check():
    guide = (CI.parents[2] / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
    assert "sha256sum -c SHA256SUMS --ignore-missing" in guide and "cosign verify-blob" in guide
