"""The feature matrix: what Kiboto Companion and Kiboto OS can each do.

docs/feature-matrix.json is the one source. This writes the two things people read from it:

    python scripts/feature_matrix.py write    docs/FEATURES.md (GitHub) and docs/features.html (the website)
    python scripts/feature_matrix.py check    exits 1 when either is behind the source

A test runs `check`, so a change to the source without `write` fails the build.
"""

from __future__ import annotations

import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "docs", "feature-matrix.json")
MARKDOWN = os.path.join(ROOT, "docs", "FEATURES.md")
PAGE = os.path.join(ROOT, "docs", "features.html")


def load(path: str | None = None) -> dict:
    with open(path or SOURCE, encoding="utf-8") as f:
        return json.load(f)


def problems(matrix: dict) -> list[str]:
    """What is wrong with the source: a missing column, an unknown state, a name used twice."""
    out, seen = [], set()
    cols = [c["id"] for c in matrix.get("columns", [])]
    states = matrix.get("states", {})
    if len(cols) != 3:
        out.append("there must be three columns")
    for group in matrix.get("groups", []):
        free_text = group["name"] == "Where it runs"  # this group says things in words, not states
        for feature in group.get("features", []):
            name = feature.get("name", "")
            if not name or name in seen:
                out.append(f"{name or 'a feature'}: no name, or the name is used twice")
            seen.add(name)
            for col in cols:
                value = feature.get(col)
                if not value:
                    out.append(f"{name}: nothing for {col}")
                elif not free_text and value not in states:
                    out.append(f"{name}: {value!r} for {col} is not one of {', '.join(states)}")
    return out


def _word(matrix: dict, value: str) -> str:
    return matrix["states"].get(value, value)


def markdown(matrix: dict) -> str:
    cols = matrix["columns"]
    lines = [
        "# What Kiboto can do, by edition",
        "",
        "<!-- Written by scripts/feature_matrix.py from docs/feature-matrix.json. Change the source, then run",
        "     `python scripts/feature_matrix.py write`. -->",
        "",
        "Kiboto runs in three ways. This page says what each can do today.",
        "",
    ]
    lines += [f"- **{c['name']}.** {c['about']}" for c in cols]
    lines += ["", "What the words mean:", ""]
    meaning = {
        "yes": "Kiboto does it.",
        "partly": "Kiboto does part of it; the note says which part.",
        "view": "Kiboto shows it; the NAS system changes it.",
        "host": "The NAS system or the Linux beside Kiboto does it, in its own settings.",
        "soon": "Not there yet on this edition; it is being built.",
        "check": "Built, and still being checked on this edition.",
        "no": "Not offered here.",
    }
    lines += [f"- **{word}**: {meaning[key]}" for key, word in matrix["states"].items()]
    for group in matrix["groups"]:
        lines += ["", f"## {group['name']}", ""]
        lines.append("| | " + " | ".join(c["short"] for c in cols) + " |")
        lines.append("| --- | " + " | ".join("---" for _ in cols) + " |")
        for feature in group["features"]:
            name = feature["name"]
            if feature.get("note"):
                name += f"<br><sub>{feature['note']}</sub>"
            lines.append(f"| {name} | " + " | ".join(_word(matrix, feature[c["id"]]) for c in cols) + " |")
    lines += [
        "",
        "Something here does not match what you see? Please open an issue: the page is kept in step with every",
        "change, and a wrong line is a bug.",
        "",
    ]
    return "\n".join(lines)


STYLE = """
:root{--bg:#f4f8f8;--card:#ffffff;--ink:#12292c;--soft:#4a6165;--line:#d5e2e3;--brand:#0f7f73;
--yes:#0f7f73;--partly:#8a5a00;--view:#3b5bb5;--host:#4a6165;--soon:#a2420f;--check:#6b4bb0;--no:#7a8789}
@media (prefers-color-scheme:dark){:root{--bg:#0d1a1c;--card:#122326;--ink:#e6f1f1;--soft:#9db3b6;--line:#23393c;
--brand:#33cdb8;--yes:#33cdb8;--partly:#f2c14e;--view:#8fb0ff;--host:#9db3b6;--soon:#ff9d6c;--check:#c3a6ff;--no:#7f9396}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1060px;margin:0 auto;padding:32px 16px 64px}a{color:var(--brand)}
h1{font-size:1.9rem;line-height:1.2;margin:8px 0 12px}h2{font-size:1.2rem;margin:36px 0 10px}
.lead{color:var(--soft);max-width:70ch}.cols{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));margin:20px 0}
.col{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.col b{display:block;margin-bottom:4px}.col span{color:var(--soft);font-size:.92rem}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:var(--card)}
table{border-collapse:collapse;width:100%;min-width:640px}
th,td{text-align:left;padding:10px 14px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}thead th{font-size:.85rem;color:var(--soft);font-weight:600}
th[scope=row]{font-weight:600;width:40%}small{display:block;font-weight:400;color:var(--soft);margin-top:2px}
.s{font-weight:600;white-space:nowrap}.s::before{content:"";display:inline-block;width:.6em;height:.6em;border-radius:50%;
background:currentColor;margin-right:.45em}.yes{color:var(--yes)}.partly{color:var(--partly)}.view{color:var(--view)}
.host{color:var(--host)}.soon{color:var(--soon)}.check{color:var(--check)}.no{color:var(--no)}
.key{display:flex;flex-wrap:wrap;gap:6px 18px;margin:8px 0 0;padding:0;list-style:none;font-size:.92rem;color:var(--soft)}
footer{margin-top:40px;color:var(--soft);font-size:.92rem}
""".strip()


def page(matrix: dict) -> str:
    cols = matrix["columns"]
    e = html.escape
    out = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>Kiboto: what each edition can do</title>",
        '<meta name="description" content="Kiboto Companion and Kiboto OS compared, feature by feature.">',
        "<!-- Written by scripts/feature_matrix.py from docs/feature-matrix.json. Do not edit by hand. -->",
        f"<style>{STYLE}</style>",
        "</head>",
        "<body>",
        "<main>",
        '<p><a href="/">Kiboto</a></p>',
        "<h1>What each edition can do</h1>",
        '<p class="lead">Kiboto runs in three ways. This page says what each can do today, and what is still on its way.</p>',
        '<div class="cols">',
    ]
    out += [f'<div class="col"><b>{e(c["name"])}</b><span>{e(c["about"])}</span></div>' for c in cols]
    out += ["</div>", '<ul class="key" aria-label="What the words mean">']
    out += [f'<li><span class="s {key}">{e(word)}</span></li>' for key, word in matrix["states"].items()]
    out.append("</ul>")
    for group in matrix["groups"]:
        out += [
            f"<h2>{e(group['name'])}</h2>",
            '<div class="scroll" tabindex="0" role="region" aria-label="' + e(group["name"]) + '">',
            "<table>",
            "<thead><tr><th></th>" + "".join(f'<th scope="col">{e(c["short"])}</th>' for c in cols) + "</tr></thead>",
            "<tbody>",
        ]
        for feature in group["features"]:
            note = f"<small>{e(feature['note'])}</small>" if feature.get("note") else ""
            cells = ""
            for c in cols:
                value = feature[c["id"]]
                if value in matrix["states"]:
                    cells += f'<td><span class="s {value}">{e(matrix["states"][value])}</span></td>'
                else:
                    cells += f"<td>{e(value)}</td>"
            out.append(f'<tr><th scope="row">{e(feature["name"])}{note}</th>{cells}</tr>')
        out += ["</tbody>", "</table>", "</div>"]
    out += [
        "<footer>This page is written from the same file as the list on GitHub, and is kept in step with every change. "
        "Kiboto OS is in beta.</footer>",
        "</main>",
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(out)


def behind(matrix: dict | None = None) -> list[str]:
    """The written files that do not match the source."""
    matrix = matrix or load()
    out = []
    for path, text in ((MARKDOWN, markdown(matrix)), (PAGE, page(matrix))):
        try:
            with open(path, encoding="utf-8") as f:
                if f.read() != text:
                    out.append(os.path.relpath(path, ROOT))
        except OSError:
            out.append(os.path.relpath(path, ROOT))
    return out


def main(argv: list[str]) -> int:
    matrix = load()
    wrong = problems(matrix)
    if wrong:
        print("\n".join(wrong), file=sys.stderr)
        return 1
    if argv[1:2] == ["write"]:
        for path, text in ((MARKDOWN, markdown(matrix)), (PAGE, page(matrix))):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            print("wrote", os.path.relpath(path, ROOT))
        return 0
    if argv[1:2] == ["check"]:
        late = behind(matrix)
        if late:
            print("behind docs/feature-matrix.json (run: python scripts/feature_matrix.py write):", ", ".join(late))
        return 1 if late else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
