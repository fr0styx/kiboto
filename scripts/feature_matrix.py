"""The feature matrix: what Kiboto Companion and Kiboto OS can each do.

docs/feature-matrix.json is the one source. This writes the two things people read from it:

    python scripts/feature_matrix.py write    docs/FEATURES.md (GitHub), docs/features.html (the website)
                                              and backend/edition_features.json (the app's cards)
    python scripts/feature_matrix.py check    exits 1 when either is behind the source

A test runs `check`, so a change to the source without `write` fails the build.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "docs", "feature-matrix.json")
MARKDOWN = os.path.join(ROOT, "docs", "FEATURES.md")
GUIDE = "https://github.com/fr0styx/kiboto/blob/main/docs/CHOOSE_AND_MOVE.md"
CHOOSE = (
    "Keep your NAS system: Companion beside it. A Linux machine with Docker and no NAS system: Companion"
    " on plain Linux. A machine you give to Kiboto entirely, with a system disk of its own: Kiboto OS."
    " Companion can move to Kiboto OS later, with its pools and a settings backup."
)
PAGE = os.path.join(ROOT, "docs", "features.html")
APP = os.path.join(ROOT, "backend", "edition_features.json")
ID = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def load(path: str | None = None) -> dict:
    with open(path or SOURCE, encoding="utf-8") as f:
        return json.load(f)


def problems(matrix: dict) -> list[str]:
    """What is wrong with the source: a missing column, an unknown state, a name used twice."""
    out, seen, ids = [], set(), set()
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
            fid = feature.get("id")
            if fid is not None and (not isinstance(fid, str) or not ID.match(fid) or fid in ids):
                out.append(f"{name}: the id {fid!r} is not a short lower-case name, or is used twice")
            ids.add(fid)
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
    lines += ["", f"{CHOOSE} [How to choose, and how to move](CHOOSE_AND_MOVE.md).", ""]
    lines += ["What the words mean:", ""]
    meaning = MEANING
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


MEANING = {
    "yes": "Kiboto does it.",
    "partly": "Kiboto does part of it; the note says which part.",
    "view": "Kiboto shows it; the NAS system changes it.",
    "host": "The NAS system or the Linux beside Kiboto does it, in its own settings.",
    "soon": "Not there yet on this edition; it is being built.",
    "check": "Built, and still being checked on this edition.",
    "no": "Not offered here.",
}


LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 4 236 56" aria-hidden="true"><g transform="translate(-6 0)"><path d="M19 6H45A13 13 0 0 1 58 19V37.5A2.5 2.5 0 0 1 55.5 40H8.5A2.5 2.5 0 0 1 6 37.5V19A13 13 0 0 1 19 6ZM8.5 42.5H55.5A2.5 2.5 0 0 1 58 45.0V45.0A13 13 0 0 1 45 58.0H19A13 13 0 0 1 6 45.0V45.0A2.5 2.5 0 0 1 8.5 42.5Z" style="fill:var(--mk-body)"/><path d="M19.0 13H45.0A6.5 6.5 0 0 1 51.5 19.5V27.0A6.5 6.5 0 0 1 45.0 33.5H19.0A6.5 6.5 0 0 1 12.5 27.0V19.5A6.5 6.5 0 0 1 19.0 13Z" style="fill:var(--mk-disp)"/><path d="M24.75 17.75H24.75A3.25 3.25 0 0 1 28.0 21.0V25.5A3.25 3.25 0 0 1 24.75 28.75H24.75A3.25 3.25 0 0 1 21.5 25.5V21.0A3.25 3.25 0 0 1 24.75 17.75Z" style="fill:var(--mk-eye)"/><path d="M39.25 17.75H39.25A3.25 3.25 0 0 1 42.5 21.0V25.5A3.25 3.25 0 0 1 39.25 28.75H39.25A3.25 3.25 0 0 1 36 25.5V21.0A3.25 3.25 0 0 1 39.25 17.75Z" style="fill:var(--mk-eye)"/><path d="M46.05 50.25A3.2 3.2 0 1 0 52.45 50.25A3.2 3.2 0 1 0 46.05 50.25Z" style="fill:var(--mk-led)"/></g><g transform="translate(70 16.5)"><g fill="none" style="stroke:var(--mk-ink)" stroke-width="6.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2V38M3 29.5L17.5 15M9.2 23.3L19 38M29.5 16V38M40 2V38M114.5 6.5V31Q114.5 38 121.5 38H123.5M108 16H123.5"/><circle cx="52" cy="26.25" r="12.25"/><circle cx="87.5" cy="26.25" r="12.25"/><circle cx="147" cy="26.25" r="12.25"/></g><circle cx="29.5" cy="5.2" r="4.1" style="fill:var(--mk-dot)"/></g></svg>"""

# The page is a page of kiboto.net: the site's own header, footer, type and colours come from its
# /site.css (kept with the site, beside index.html); only the table's own look is here.
STYLE = """
:root{--st-view:#3b5bb5;--st-soon:#a2420f;--st-check:#6b4bb0}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--st-view:#8fb0ff;--st-soon:#ff9d6c;--st-check:#c3a6ff}}
:root[data-theme="dark"]{--st-view:#8fb0ff;--st-soon:#ff9d6c;--st-check:#c3a6ff}
.page-head{padding-block:64px 8px}
.page-head h1{font-size:clamp(34px,4.4vw,52px);line-height:1.08}
.page-head .head p{font-size:18px}
.choose{margin-top:28px;max-width:46em;color:var(--muted)}
.key{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px 32px;margin:28px 0 0;padding:0;list-style:none}
.key li{display:flex;flex-direction:column;gap:2px;font-size:15px;color:var(--muted)}
.st{font-family:var(--font-mono);font-size:13.5px;display:inline-flex;gap:8px;align-items:center;white-space:nowrap}
.st::before{content:"";width:8px;height:8px;border-radius:50%;background:currentColor;flex:none}
.s-yes{color:var(--primary-text)}.s-partly{color:var(--accent-text)}.s-view{color:var(--st-view)}
.s-host,.s-no{color:var(--muted)}.s-soon{color:var(--st-soon)}.s-check{color:var(--st-check)}
.group{padding-block:44px}
.group h2{font-size:clamp(24px,2.6vw,30px)}
.fm{width:100%;border-collapse:collapse;margin-top:18px;font-size:16px;font-variant-numeric:tabular-nums}
.fm th,.fm td{text-align:left;vertical-align:top;padding:14px 12px 14px 0;border-top:1px solid var(--line)}
.fm thead th{font-family:var(--font-mono);font-weight:400;font-size:13px;color:var(--muted);border-top:0;padding-top:0}
.fm tbody th{font-weight:700;width:42%}
.fm tbody th small{display:block;font-weight:400;font-size:14.5px;color:var(--muted);margin-top:4px;max-width:34em}
@media (max-width:760px){
.fm thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.fm,.fm tbody,.fm tr,.fm th,.fm td{display:block;width:auto}
.fm tr{border-top:1px solid var(--line);padding:14px 0}
.fm th,.fm td{border:0;padding:3px 0}
.fm td{display:flex;justify-content:space-between;align-items:baseline;gap:16px}
.fm td::before{content:attr(data-col);color:var(--muted);font-size:14.5px;flex:1}
.fm tbody th{width:auto}
.fm td .st{white-space:normal;text-align:right}
}
"""


def _header(e) -> list[str]:
    return [
        '<header class="top">',
        '  <div class="in">',
        f'    <a class="logo" href="/" aria-label="Kiboto home">{LOGO}</a>',
        '    <span class="stage-tag">Beta</span>',
        '    <nav aria-label="Main">',
        '      <a href="/#what">What it is</a>',
        '      <a href="/#features">Features</a>',
        '      <a href="/features/" aria-current="page">Editions</a>',
        '      <a href="/#kib">Kib</a>',
        '      <a href="/#download" class="keep">Get Kiboto</a>',
        "    </nav>",
        "  </div>",
        "</header>",
    ]


def _footer() -> list[str]:
    return [
        "<footer>",
        '  <div class="in">',
        f'    <a class="logo" href="/" aria-label="Kiboto home">{LOGO}</a>',
        "    <p>kiboto.net · MIT license</p>",
        '    <nav aria-label="Footer">',
        '      <a href="https://github.com/fr0styx/kiboto">GitHub</a>',
        '      <a href="/features/" aria-current="page">What each edition can do</a>',
        '      <a href="https://github.com/fr0styx/kiboto/releases">Releases</a>',
        '      <a href="https://github.com/fr0styx/kiboto/blob/main/docs/PRIVACY.md">Privacy</a>',
        "    </nav>",
        "  </div>",
        "</footer>",
    ]


def page(matrix: dict) -> str:
    cols = matrix["columns"]
    e = html.escape
    fonts = (
        "https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:wght@400;700"
        "&family=Atkinson+Hyperlegible+Mono:wght@400;700&family=M+PLUS+Rounded+1c:wght@800&display=swap"
    )
    out = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
        "<!-- Written by scripts/feature_matrix.py from docs/feature-matrix.json. Do not edit by hand. -->",
        '<meta name="theme-color" content="#f3f6f6" media="(prefers-color-scheme: light)">',
        '<meta name="theme-color" content="#0a1113" media="(prefers-color-scheme: dark)">',
        "<title>Kiboto: what each edition can do</title>",
        '<meta name="description" content="Kiboto Companion and Kiboto OS compared, feature by feature.">',
        '<link rel="canonical" href="https://kiboto.net/features/">',
        '<link rel="icon" href="/favicon.ico" sizes="48x48">',
        '<link rel="icon" href="/icons/favicon.svg" type="image/svg+xml">',
        '<link rel="preconnect" href="https://fonts.googleapis.com">',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        f'<link rel="stylesheet" href="{e(fonts)}">',
        '<link rel="stylesheet" href="/site.css">',
        f"<style>{STYLE}</style>",
        "</head>",
        "<body>",
        '<a class="skip" href="#editions-list">Skip to the list</a>',
        *_header(e),
        "<main>",
        '<section class="page-head" id="editions-list">',
        '  <div class="in">',
        '    <div class="head">',
        "      <h1>What each edition can do</h1>",
        "      <p>Kiboto runs in three ways. This page says what each can do today, and what is still on its way.</p>",
        "    </div>",
        '    <div class="eds">',
    ]
    for c in cols:
        out += [
            '      <div class="ed">',
            f"        <h3>{e(c['name'])}</h3>",
            f"        <p>{e(c['about'])}</p>",
            "      </div>",
        ]
    out += [
        "    </div>",
        f'    <p class="choose">{e(CHOOSE)} <a href="{GUIDE}">How to choose, and how to move</a>.</p>',
        '    <ul class="key" aria-label="What the words mean">',
    ]
    out += [
        f'      <li><span class="st s-{key}">{e(word)}</span> {e(MEANING[key])}</li>'
        for key, word in matrix["states"].items()
    ]
    out += ["    </ul>", "  </div>", "</section>"]
    for n, group in enumerate(matrix["groups"]):
        out += [
            f'<section class="group{" alt" if n % 2 == 0 else ""}">',
            '  <div class="in">',
            f"    <h2>{e(group['name'])}</h2>",
            '    <table class="fm">',
            '      <thead><tr><th scope="col">Feature</th>'
            + "".join(f'<th scope="col">{e(c["short"])}</th>' for c in cols)
            + "</tr></thead>",
            "      <tbody>",
        ]
        for feature in group["features"]:
            note = f"<small>{e(feature['note'])}</small>" if feature.get("note") else ""
            cells = ""
            for c in cols:
                value = feature[c["id"]]
                label = f' data-col="{e(c["short"])}"'
                if value in matrix["states"]:
                    cells += f'<td{label}><span class="st s-{value}">{e(matrix["states"][value])}</span></td>'
                else:
                    cells += f"<td{label}>{e(value)}</td>"
            out.append(f'        <tr><th scope="row">{e(feature["name"])}{note}</th>{cells}</tr>')
        out += ["      </tbody>", "    </table>", "  </div>", "</section>"]
    out += [
        '<section class="band">',
        '  <div class="in">',
        '    <p class="choose">This page is written from the same file as the list on GitHub, and kept in step with every change. Kiboto OS is in beta. Something here does not match what you see? <a href="https://github.com/fr0styx/kiboto/issues">Open an issue</a>: a wrong line is a bug.</p>',
        "  </div>",
        "</section>",
        "</main>",
        *_footer(),
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(out)


def app(matrix: dict) -> str:
    """What the app reads: each feature with an id, and its state on each of the three columns."""
    cols = [c["id"] for c in matrix["columns"]]
    table = {f["id"]: {c: f[c] for c in cols} for g in matrix["groups"] for f in g["features"] if f.get("id")}
    about = "Written by scripts/feature_matrix.py from docs/feature-matrix.json. Do not edit by hand."
    return json.dumps({"_about": about, "features": table}, indent=1, sort_keys=True) + "\n"


def written(matrix: dict) -> tuple[tuple[str, str], ...]:
    return ((MARKDOWN, markdown(matrix)), (PAGE, page(matrix)), (APP, app(matrix)))


def behind(matrix: dict | None = None) -> list[str]:
    """The written files that do not match the source."""
    matrix = matrix or load()
    out = []
    for path, text in written(matrix):
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
        for path, text in written(matrix):
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
