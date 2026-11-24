"""ADR 0006: no new place in the backend starts a system program by itself.

Once Kiboto's web process runs as the user kiboto (step 9), a program it starts runs without root
too; what needs root goes through the host door. Each file's count of the places that start a
program is held in tests/adr6_spawn_baseline.json: a new one fails here. Route it through the door
(services/host_door.py) or, for a program that needs no root (reading, converting, a tool of the
app's own), raise that file's count in the baseline in the same change and say why in it. A count
that went down is written down too, so the baseline stays tight.

    python -m pytest tests/test_adr6_spawns.py   # KIBOTO_UPDATE_SPAWNS=1 writes the counts"""

import ast
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "adr6_spawn_baseline.json"
SUBPROCESS = {"run", "Popen", "check_output", "check_call", "call", "getoutput", "getstatusoutput"}
OS = {"system", "popen", "execv", "execvp", "execve", "execl", "execlp", "spawnv", "spawnvp", "posix_spawn"}
ASYNCIO = {"create_subprocess_exec", "create_subprocess_shell"}


def _spawns(tree: ast.AST) -> int:
    n = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            mod, name = f.value.id, f.attr
            if (
                (mod == "subprocess" and name in SUBPROCESS)
                or (mod == "os" and name in OS)
                or (mod == "asyncio" and name in ASYNCIO)
            ):
                n += 1
        elif isinstance(f, ast.Name) and f.id == "run_bounded":
            n += 1
    return n


def counts() -> dict[str, int]:
    out = {}
    for path in sorted((ROOT / "backend").rglob("*.py")):
        n = _spawns(ast.parse(path.read_text(encoding="utf-8")))
        if n:
            out[str(path.relative_to(ROOT))] = n
    return out


def test_no_new_place_starts_a_program():
    now = counts()
    if os.environ.get("KIBOTO_UPDATE_SPAWNS") == "1":
        BASELINE.write_text(json.dumps(now, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    held = json.loads(BASELINE.read_text(encoding="utf-8"))
    more = {f: (held.get(f, 0), n) for f, n in now.items() if n > held.get(f, 0)}
    assert not more, (
        "these files start more programs than tests/adr6_spawn_baseline.json holds "
        "(route it through the host door, ADR 0006, or raise the count there and say why): "
        + ", ".join(f"{f} {a} -> {b}" for f, (a, b) in sorted(more.items()))
    )
    fewer = {f: (n, now.get(f, 0)) for f, n in held.items() if now.get(f, 0) < n}
    assert not fewer, "fewer than the baseline holds, lower it (KIBOTO_UPDATE_SPAWNS=1): " + ", ".join(
        f"{f} {a} -> {b}" for f, (a, b) in sorted(fewer.items())
    )


def test_the_counter_sees_each_way_of_starting_a_program():
    src = """
import subprocess, os, asyncio
subprocess.run(["x"]); subprocess.Popen(["x"]); os.system("x"); run_bounded(["x"], timeout=1)
asyncio.create_subprocess_exec("x"); subprocess.check_output(["x"])
"""
    assert _spawns(ast.parse(src)) == 6
