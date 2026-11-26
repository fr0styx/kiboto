"""Lists the third-party packages bundled in Kiboto's image, with their licences.

    python scripts/third_party.py [package-lock.json] > third-party-licences.txt

Run at image build time (Dockerfile), so the list is always that image's: the Python packages
installed in it (from their metadata), the frontend packages compiled into its pages (from
package-lock.json, those that are not development tools), and the operating system's Debian
packages with their versions (dpkg), with where Debian publishes their source and the project's
written offer for the GPL source, as the install USB image's NOTICE.txt makes it."""

from __future__ import annotations

import importlib.metadata
import json
import shutil
import subprocess
import sys

UNKNOWN = "see the package"


def _python_licence(meta) -> str:
    expr = (meta.get("License-Expression") or "").strip()
    if expr:
        return expr
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    classifiers = [c for c in classifiers if c != "OSI Approved"]
    if classifiers:
        return ", ".join(sorted(set(classifiers)))
    text = (meta.get("License") or "").strip()
    return text if text and "\n" not in text and len(text) <= 60 else UNKNOWN


def python_packages() -> list[tuple[str, str, str]]:
    seen = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name") or ""
        if name and name.lower() not in seen:
            seen[name.lower()] = (name, dist.version, _python_licence(dist.metadata))
    return sorted(seen.values(), key=lambda r: r[0].lower())


def frontend_packages(lock_path: str) -> list[tuple[str, str, str]]:
    with open(lock_path, encoding="utf-8") as f:
        packages = json.load(f).get("packages") or {}
    rows = []
    for path, info in packages.items():
        if not path or info.get("dev") or info.get("devOptional"):
            continue
        name = path.rsplit("node_modules/", 1)[-1]
        rows.append((name, str(info.get("version") or ""), str(info.get("license") or UNKNOWN)))
    return sorted(set(rows), key=lambda r: r[0].lower())


def debian_packages() -> list[tuple[str, str]]:
    """The image's Debian packages and their versions; none where there is no dpkg (a test)."""
    if not shutil.which("dpkg-query"):
        return []
    done = subprocess.run(  # noqa: S603,S607
        ["dpkg-query", "-W", "-f=${binary:Package} ${Version}\\n"], capture_output=True, text=True, check=False
    )
    rows = [tuple(line.split(" ", 1)) for line in done.stdout.splitlines() if " " in line]
    return sorted((name, version) for name, version in rows)


OS_NOTICE = [
    "The operating system in this image is Debian 13. Debian and the software in it are free",
    "software under their own licences, mostly the GNU General Public License; each package's",
    "licence is in /usr/share/doc/<package>/copyright inside the image. Debian publishes the source",
    "code of every package it has published, by version: https://snapshot.debian.org/",
    "",
    "Two parts come from outside Debian's main section:",
    "- the ZFS tools (zfsutils-linux and its libraries, full image only), from Debian's",
    "  trixie-backports, under the CDDL;",
    "- Intel's media driver (intel-media-va-driver-non-free, amd64 only), for converting videos",
    "  with Intel Quick Sync. Its own licence is Expat (MIT-style); Debian files it as non-free",
    "  because its GPU kernels come without source. It is used only when /dev/dri is passed in.",
    "",
    "Written offer: for three years after a Kiboto release carrying this image was published, the",
    "Kiboto project gives anyone who asks the complete corresponding source code of the GPL and LGPL",
    "software in this image, for no more than the cost of making and sending the copy. Ask in an",
    'issue titled "Source request" at https://github.com/fr0styx/kiboto/issues, naming the Kiboto',
    "release. Kiboto adds no change to any of that software.",
    "",
]


def render(
    python: list[tuple[str, str, str]],
    frontend: list[tuple[str, str, str]],
    debian: list[tuple[str, str]] | None = None,
) -> str:
    out = [
        "Third-party software in this Kiboto image",
        "",
        "Kiboto itself is under the MIT licence (LICENSE in its repository).",
        "",
        *OS_NOTICE,
    ]
    for title, rows in (("Python packages", python), ("Frontend packages", frontend)):
        out += [f"{title} ({len(rows)})", ""]
        out += [f"{name} {version}: {licence}" for name, version, licence in rows]
        out.append("")
    debian = debian or []
    out += [f"Debian packages ({len(debian)}), with the versions to find their source by", ""]
    out += [f"{name} {version}" for name, version in debian]
    out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    frontend = frontend_packages(argv[1]) if len(argv) > 1 else []
    sys.stdout.write(render(python_packages(), frontend, debian_packages()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
