"""Writes RELEASE_NOTES.md and the release title for a tag from CHANGELOG.md.

The notes are everything under "## <tag> ..." up to the next "## v" entry, so the
"####" sections inside an entry are kept. Relative links become links to the tagged files.
Within each section, the entries that concern only Kiboto OS (a machine of Kiboto's own) go last,
under "Kiboto OS only", so someone who runs the container reads what is theirs first.
"""

import os
import re
import sys

OS_ONLY = re.compile(
    r"^-\s+(\*\*)?(Kiboto OS\b|On a machine of its own|On a machine Kiboto runs|For a machine of its own)",
    re.IGNORECASE,
)


def by_edition(notes: str) -> str:
    """Each "####" section with its Kiboto OS entries moved under "##### Kiboto OS only" at its end.
    An entry is a "- " line with the lines that continue it; "Before you upgrade" stays as written."""
    out: list[str] = []
    section: list[str] = []
    heading = ""

    def flush() -> None:
        if not heading or "before you upgrade" in heading.lower():
            out.extend(section)
            return
        entries: list[list[str]] = []
        rest: list[str] = []
        for line in section:
            if line.startswith("- "):
                entries.append([line])
            elif entries and (line.startswith(("  ", "\t")) or (line.strip() and not line.startswith("#"))):
                entries[-1].append(line)
            elif not line.strip():
                (entries[-1] if entries else rest).append(line)
            else:
                rest.append(line)
        both = [e for e in entries if not OS_ONLY.match(e[0])]
        only_os = [e for e in entries if OS_ONLY.match(e[0])]
        out.extend(rest)
        for e in both:
            out.extend(e)
        if only_os and both:
            if out and out[-1].strip():
                out.append("")
            out.extend(["##### Kiboto OS only", ""])
        for e in only_os:
            out.extend(e)

    for line in notes.splitlines():
        if line.startswith("#### "):
            flush()
            out.append(line)
            section, heading = [], line
        elif heading:
            section.append(line)
        else:
            out.append(line)
    flush()
    return "\n".join(out).strip()


def extract(text: str, tag: str, repo: str = ""):
    m = re.search(rf"^##\s+{re.escape(tag)}\b.*?\n(.*?)(?=^##\s+v\d|\Z)", text, re.DOTALL | re.MULTILINE)
    if not m:
        return tag, ""
    notes = m.group(1).strip()
    notes = by_edition(re.sub(r"\n-{3,}\s*$", "", notes).strip())
    if repo:
        notes = re.sub(
            r"\]\((?!https?://|#|mailto:)([^)\s]+)\)",
            lambda mm: f"](https://github.com/{repo}/blob/{tag}/{mm.group(1).lstrip('./')})",
            notes,
        )
    title = tag
    first = notes.splitlines()[0].strip() if notes else ""
    if first.startswith("###"):
        clean = re.sub(r"^[^\w\s\(\)]+\s*", "", re.sub(r"^###\s*", "", first)).strip()
        if clean:
            title = f"{tag} - {clean}"
    return title, notes


def main():
    tag = os.environ.get("GITHUB_REF_NAME", "") or (sys.argv[1] if len(sys.argv) > 1 else "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    text = ""
    if os.path.exists("CHANGELOG.md"):
        with open("CHANGELOG.md", encoding="utf-8") as f:
            text = f.read()
    title, notes = extract(text, tag, repo)
    with open("RELEASE_NOTES.md", "w", encoding="utf-8") as out:
        out.write(notes)
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as gh_out:
        gh_out.write(f"title={title}\n")
    print(title)


if __name__ == "__main__":
    main()
