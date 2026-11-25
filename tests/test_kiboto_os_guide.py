"""Kiboto OS has a guide of its own, and it says what the install script enforces."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = (ROOT / "docs" / "KIBOTO_OS.md").read_text(encoding="utf-8")
INSTALL = (ROOT / "packaging" / "install.sh").read_text(encoding="utf-8")


def test_the_install_guide_and_readme_point_at_it():
    assert "(KIBOTO_OS.md)" in (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
    assert "(docs/KIBOTO_OS.md)" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_it_names_what_the_script_refuses():
    assert "= amd64 ] || die" in INSTALL and "amd64" in GUIDE
    assert 'VERSION_ID:-}" = 13' in INSTALL and "Debian 13" in GUIDE
    assert "secure_boot_on" in INSTALL and "Secure Boot off" in GUIDE


def test_the_hardware_report_it_points_at_exists():
    assert "hardware_report.sh" in GUIDE
    assert (ROOT / "scripts" / "hardware_report.sh").is_file()


def test_its_own_links_land_on_its_headings():
    headings = {re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-") for h in re.findall(r"^## (.+)$", GUIDE, re.M)}
    for anchor in re.findall(r"\]\(#([^)]+)\)", GUIDE):
        assert anchor in headings, anchor
