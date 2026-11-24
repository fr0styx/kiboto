"""A second opinion on the eval's answers (AI-28): a larger local model grades each answer against
the question, the facts it should give and the file it comes from.

Decided 10 Nov 2026: the judge is a larger model on the same machine (Qwen3 8B through Ollama, on
the CPU), with no outside key or service. It is less independent than another vendor's model, so
its grades are reported next to the rule-based scores (run_eval.answer_matches), never instead of
them, and the places where the two disagree are listed for a person to look at.

Nothing is pulled or changed on the judge's server: without the model there, judge_available is
False and the eval runs without it.
"""

import json
import os
import time
import urllib.request
from collections.abc import Callable
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")
GRADES = ("correct", "partly", "wrong", "declined")
SOURCE_CHARS = 2500  # of each file the answer should come from; the judge's context stays small

SYSTEM = (
    "You grade the answers of a home NAS assistant that answers from the household's own files. "
    'Reply with JSON only: {"grade": "correct" | "partly" | "wrong" | "declined", '
    '"supported": true | false, "why": "<one short sentence>"}. '
    "correct: the answer gives what the expected facts say (other words, units or languages are fine). "
    "partly: some of it, or with a wrong detail. wrong: another or an invented answer. "
    "declined: it says it does not know or that the files do not say. "
    "supported: everything the answer claims is in the source text (true when it declined)."
)

Post = Callable[[str, dict[str, Any], float], dict[str, Any]]


def _post(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (the runner's own model server)
        return json.load(r)


def judge_available(host: str, model: str, timeout: float = 5.0) -> bool:
    """The judge's model is on its server already (it is never pulled from here)."""
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=timeout) as r:  # noqa: S310
            names = {m.get("name") for m in json.load(r).get("models") or []}
    except (OSError, ValueError):
        return False
    return model in names or f"{model}:latest" in names


def source_text(relevant: list[str], corpus: str = CORPUS) -> str:
    parts = []
    for rel in relevant[:3]:
        path = os.path.normpath(os.path.join(corpus, rel))
        if not path.startswith(os.path.normpath(corpus) + os.sep):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                parts.append(f"--- {rel}\n{f.read(SOURCE_CHARS)}")
        except OSError:
            parts.append(f"--- {rel}\n(the file is made while the eval runs; its text is not here)")
    return "\n\n".join(parts) or "(no source file)"


def prompt(row: dict[str, Any], corpus: str = CORPUS) -> str:
    if row.get("unanswerable"):
        expected = "The files do not answer this question: the right answer declines."
    else:
        expected = "Any of: " + "; ".join(row.get("expected") or [])
        if row.get("expected_all"):
            expected += "\nAll of: " + "; ".join(row["expected_all"])
    return (
        f"Question: {row['question']}\n\nExpected facts:\n{expected}\n\n"
        f"Source text:\n{source_text(row.get('relevant') or [], corpus)}\n\n"
        f"Answer to grade:\n{row.get('answer') or '(empty)'}"
    )


def grade_one(row: dict[str, Any], host: str, model: str, post: Post = _post, corpus: str = CORPUS) -> dict[str, Any]:
    body = {
        "model": model,
        "stream": False,
        "format": "json",
        "think": False,
        # on the CPU: the iGPU already carries the model servers, and more on it froze the NAS
        "options": {"temperature": 0, "num_ctx": 8192, "num_gpu": 0},
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt(row, corpus)}],
    }
    try:
        said = json.loads((post(f"{host}/api/chat", body, 600.0).get("message") or {}).get("content") or "{}")
    except (OSError, ValueError) as e:
        return {"id": row["id"], "grade": None, "why": f"no grade: {type(e).__name__}"}
    grade = said.get("grade") if said.get("grade") in GRADES else None
    return {
        "id": row["id"],
        "grade": grade,
        "supported": bool(said.get("supported")),
        "why": str(said.get("why") or "")[:200],
    }


def right(row: dict[str, Any], graded: dict[str, Any]) -> bool:
    """What the judge counts as right: the facts given, or a refusal where the files have no answer."""
    return graded["grade"] == ("declined" if row.get("unanswerable") else "correct")


def judge(
    rows: list[dict[str, Any]],
    host: str,
    model: str,
    post: Post = _post,
    minutes: float = 30.0,
    corpus: str = CORPUS,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Grades the answer rows (run_eval's answer_rows) until `minutes` run out; the summary sits next
    to the rule-based scores, with the answers where judge and rules disagree."""
    deadline = clock() + minutes * 60
    done = []
    for row in rows:
        if clock() > deadline:
            break
        done.append((row, grade_one(row, host, model, post, corpus)))
    graded = [(r, g) for r, g in done if g["grade"]]
    n = len(graded) or 1
    return {
        "model": model,
        "asked": len(done),
        "graded": len(graded),
        "of": len(rows),
        "right": round(sum(right(r, g) for r, g in graded) / n, 3),
        "partly": round(sum(g["grade"] == "partly" for _, g in graded) / n, 3),
        "supported": round(sum(g["supported"] for _, g in graded) / n, 3),
        "agrees_with_rules": round(sum(right(r, g) == bool(r.get("auto_correct")) for r, g in graded) / n, 3),
        "disagree": [
            {"id": r["id"], "rules": bool(r.get("auto_correct")), "judge": g["grade"], "why": g["why"]}
            for r, g in graded
            if right(r, g) != bool(r.get("auto_correct"))
        ],
        "rows": [g for _, g in done],
    }
