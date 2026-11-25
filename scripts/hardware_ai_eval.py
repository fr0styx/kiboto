"""The AI check on real hardware (AI-16, PERF-10), for the self-hosted runner.

Runs the search and answer eval (tests/rag_eval) against the model servers a Kiboto install
actually uses (the embedder and the chat server, read-only: nothing is installed, pulled or
changed on them) and compares with the last recorded result of this machine.

    /opt/kb-eval/bin/python scripts/hardware_ai_eval.py \\
        --embedder http://kiboto-eg2:11434 --embedding-model embeddinggemma-2-ov --dim 768 \\
        --chat http://kiboto-ovms:8000/v1 --chat-model Qwen3-4B

With the judge's model on the runner's Ollama (--judge-model, never pulled from here), a larger
local model also grades every answer (tests/rag_eval/judge.py, AI-28); its grades are written next
to the scores, not compared against a baseline.

The public log says only PASS, FAIL or SKIP per set (the repository's Actions logs are public
and must not carry numbers from a private server). Results and baselines are written to
--results/ai on the machine: the first run of a set, a run with another model, or a run on other
questions (the eval's files and scoring code changed, questions_id) records the baseline. A set
fails when a score drops by more than --tolerance.
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETS = ("all", "documents")  # base + extended, and long / Office / scanned / multi-hop


def _isolated_env() -> None:
    """The app's code runs here without its data folder or the host's devices."""
    tmp = tempfile.mkdtemp(prefix="kiboto-ai-eval-")
    for name in ("data", "pool", "sys", "dev", "proc"):
        os.makedirs(os.path.join(tmp, name), exist_ok=True)
    os.environ.update(
        {
            "DATA_DIR": os.path.join(tmp, "data"),
            "POOL_PATH": os.path.join(tmp, "pool"),
            "BROWSE_ROOTS": os.path.join(tmp, "pool"),
            "HOST_SYS": os.path.join(tmp, "sys"),
            "HOST_DEV": os.path.join(tmp, "dev"),
            "HOST_PROC": os.path.join(tmp, "proc"),
            "ENABLE_FB": "0",
            "LED_PORT": os.path.join(tmp, "dev", "none"),
        }
    )


def lock_matches(lock_path: str, recorded_path: str = "/opt/kb-eval/lock.sha256") -> bool:
    """The runner's packages were installed from this checkout's requirements.lock."""
    try:
        with open(lock_path, "rb") as f:
            now = hashlib.sha256(f.read()).hexdigest()
        with open(recorded_path, encoding="utf-8") as f:
            return f.read().strip() == now
    except OSError:
        return False


# What is measured: the questions, the files they are asked about and how answers are scored. The
# app's own code is not in it, so a change there is compared with the baseline.
QUESTION_FILES = ("run_eval.py", "documents.py", "id_docs.py")


def questions_id(root: str = ROOT) -> str:
    """A fingerprint of the eval's questions, files and scoring code: scores taken on other questions
    are not comparable (a harder set, a new held-out split), so a change records a new baseline."""
    base = os.path.join(root, "tests", "rag_eval")
    paths = [os.path.join(base, n) for n in QUESTION_FILES]
    paths += [
        os.path.join(base, n) for n in os.listdir(base) if n.endswith(".json") and n.startswith(("queries", "qa"))
    ]
    for top, _dirs, files in os.walk(os.path.join(base, "corpus")):
        paths += [os.path.join(top, n) for n in files]
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(os.path.relpath(p, base).encode() + b"\0")
        with open(p, "rb") as fh:
            h.update(hashlib.sha256(fh.read()).digest())
    return h.hexdigest()[:16]


def reachable(url: str, timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def scores(result: dict) -> dict:
    """What a run is judged on (the per-query detail stays out of the baseline)."""
    keep = {k: result[k] for k in ("model", "set", "overall", "by_kind", "by_language", "by_split") if k in result}
    if "answers" in result:
        keep["answers"] = {k: v for k, v in result["answers"].items() if k != "wrong"}
    return keep


def verdict(now: dict, base: dict | None, chat_model: str, tolerance: float) -> tuple[str, list[str]]:
    """('PASS' | 'FAIL' | 'RECORDED', reasons). A first run, another model or other questions record
    a baseline."""
    from tests.rag_eval.compare import drops

    if not base or base.get("model") != now.get("model") or (base.get("answers") or {}).get("model") != chat_model:
        return "RECORDED", []
    if base.get("questions") != now.get("questions"):
        return "RECORDED", ["the questions changed"]
    found = drops(now, base, tolerance)
    return ("FAIL" if found else "PASS"), found


def second_opinion(result: dict, out_path: str, host: str, model: str, minutes: float) -> str:
    """The judge's grades for a set's answers, written to `out_path`. Returns the public log line
    (no numbers: the repository's Actions logs are public)."""
    from tests.rag_eval import judge

    rows = result.get("answer_rows") or []
    if not rows:
        return "SKIP ai-judge (no answers to grade)"
    if not judge.judge_available(host, model):
        return f"SKIP ai-judge (the judge's model {model} is not on the runner's Ollama)"
    graded = judge.judge(rows, host, model, minutes=minutes)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graded, f, ensure_ascii=False, indent=1)
    return f"PASS ai-judge ({graded['graded']} of {graded['of']} answers graded)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--embedder", default="http://kiboto-eg2:11434")
    ap.add_argument("--embedding-model", default="embeddinggemma-2-ov")
    ap.add_argument("--dim", type=int, default=768)
    ap.add_argument("--chat", default="http://kiboto-ovms:8000/v1")
    ap.add_argument("--chat-model", default="Qwen3-4B")
    ap.add_argument("--results", default=os.environ.get("HW_RESULTS_DIR", "/results"))
    ap.add_argument("--tolerance", type=float, default=0.03)
    ap.add_argument("--sets", default=",".join(SETS))
    ap.add_argument("--judge", default="http://kiboto-ollama:11434")
    ap.add_argument("--judge-model", default="qwen3:8b")
    ap.add_argument("--judge-minutes", type=float, default=30.0)
    args = ap.parse_args(argv)

    if not lock_matches(os.path.join(ROOT, "requirements.lock")):
        print("SKIP ai-eval (the runner image is behind requirements.lock: rebuild it, docs/HARDWARE_RUNNER.md)")
        return 0
    if not reachable(f"{args.embedder}/api/tags") or not reachable(f"{args.chat}/models"):
        print("SKIP ai-eval (the model servers are not reachable from the runner)")
        return 0

    _isolated_env()
    sys.path.insert(0, ROOT)
    from tests.rag_eval.run_eval import evaluate

    out_dir = os.path.join(args.results, "ai")
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d-%H%M")
    failed = False
    asked = questions_id()
    for name in [s for s in args.sets.split(",") if s]:
        try:
            result = evaluate(
                model=args.embedding_model,
                dim=args.dim,
                which=name,
                host=args.embedder,
                answers_model=args.chat_model,
                llm_host=args.chat,
            )
        except Exception as e:  # the log stays free of details; the file gets them
            with open(os.path.join(out_dir, f"{stamp}-{name}-error.txt"), "w", encoding="utf-8") as f:
                f.write(f"{type(e).__name__}: {e}\n")
            print(f"FAIL ai-eval {name} (the eval did not finish)")
            failed = True
            continue
        now = {**scores(result), "questions": asked}
        with open(os.path.join(out_dir, f"{stamp}-{name}.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        print(
            second_opinion(
                result,
                os.path.join(out_dir, f"{stamp}-{name}-judge.json"),
                args.judge,
                args.judge_model,
                args.judge_minutes,
            )
        )
        base_path = os.path.join(out_dir, f"baseline_{name}.json")
        try:
            with open(base_path, encoding="utf-8") as f:
                base = json.load(f)
        except (OSError, ValueError):
            base = None
        state, reasons = verdict(now, base, args.chat_model, args.tolerance)
        if state == "RECORDED":
            with open(base_path, "w", encoding="utf-8") as f:
                json.dump(now, f, ensure_ascii=False, indent=1)
            why = "the questions changed: " if reasons else ""
            print(f"PASS ai-eval {name} ({why}baseline recorded)")
        else:
            print(f"{state} ai-eval {name}")
            if reasons:
                failed = True
                with open(os.path.join(out_dir, f"{stamp}-{name}-worse.txt"), "w", encoding="utf-8") as f:
                    f.write("\n".join(reasons) + "\n")
                print(f"::warning title=AI eval::{name} scored lower than this machine's baseline")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
