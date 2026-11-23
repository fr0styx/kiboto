"""Lists the third-party packages bundled in Kiboto's image, with their licences.

    python scripts/third_party.py [package-lock.json] > third-party-licences.txt

Run at image build time (Dockerfile), so the list is always that image's: the Python packages
installed in it (from their metadata) and the frontend packages compiled into its pages (from
package-lock.json, those that are not development tools). The operating system packages of the
image keep their licences in /usr/share/doc/<package>/copyright."""

from __future__ import annotations

import importlib.metadata
import json
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


def render(python: list[tuple[str, str, str]], frontend: list[tuple[str, str, str]]) -> str:
    out = [
        "Third-party software in this Kiboto image",
        "",
        "Kiboto itself is under the MIT licence (LICENSE in its repository).",
        "The operating system packages keep their licences in /usr/share/doc/<package>/copyright.",
        "",
    ]
    for title, rows in (("Python packages", python), ("Frontend packages", frontend)):
        out += [f"{title} ({len(rows)})", ""]
        out += [f"{name} {version}: {licence}" for name, version, licence in rows]
        out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    frontend = frontend_packages(argv[1]) if len(argv) > 1 else []
    sys.stdout.write(render(python_packages(), frontend))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
