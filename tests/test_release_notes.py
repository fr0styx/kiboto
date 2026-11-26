"""The release job publishes the whole changelog entry for a tag."""

import importlib.util
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("ern", os.path.join(ROOT, "scripts", "extract_release_notes.py"))
ern = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ern)


def test_entry_keeps_subsections_and_stops_at_next_version():
    text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()  # noqa: SIM115
    from backend import __version__

    tag = f"v{__version__}"
    title, notes = ern.extract(text, tag, "fr0styx/zettnas-toolkit")
    assert title.startswith(f"{tag} - ")
    assert "#### " in notes  # subsections are kept
    assert "## v" not in notes and not notes.rstrip().endswith("---")
    assert "](docs/" not in notes and "](SECURITY.md" not in notes  # links are absolute


def test_unknown_tag_gives_empty_notes():
    assert ern.extract("## v1.0.0 (x)\n### hi\nbody\n", "v9.9.9") == ("v9.9.9", "")


def test_changelog_mentions_nobody():
    # GitHub reads a bare @name in release notes as a mention and lists that account as a contributor
    text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()  # noqa: SIM115
    prose = re.sub(r"`[^`\n]*`", "", re.sub(r"```.*?```", "", text, flags=re.S))
    mentions = sorted(set(re.findall(r"(?<![\w/])@([A-Za-z0-9][A-Za-z0-9-]*)", prose)))
    assert mentions == [], f"put these in `code`: {mentions}"


def test_kiboto_os_entries_come_last_in_each_section():
    notes = """### Title

Intro.

#### Fixes

- Kiboto OS: the firewall keeps its rules.
- A share's name may hold a dot.
  It wraps here.
- On a machine of its own, updates check the image.

#### New

- Kib floats in a corner.

#### Before you upgrade

- **Kiboto OS:** the kernel follows Debian.
- **The image name** changed."""
    out = ern.by_edition(notes)
    fixes = out[out.index("#### Fixes") : out.index("#### New")]
    assert fixes.index("A share's name") < fixes.index("##### Kiboto OS only") < fixes.index("Kiboto OS: the firewall")
    assert "  It wraps here." in fixes.split("##### Kiboto OS only")[0]  # an entry keeps its own lines
    assert "On a machine of its own" in fixes.split("##### Kiboto OS only")[1]
    new = out[out.index("#### New") : out.index("#### Before")]
    assert "Kiboto OS only" not in new  # nothing to split
    before = out[out.index("#### Before") :]
    assert before.index("**Kiboto OS:**") < before.index("**The image name**")  # left as written
    assert out.startswith("### Title\n\nIntro.")


def test_a_section_of_only_kiboto_os_entries_needs_no_subheading():
    out = ern.by_edition("#### Fixes\n\n- Kiboto OS: one.\n- Kiboto OS: two.")
    assert "##### Kiboto OS only" not in out and out.count("- Kiboto OS") == 2
