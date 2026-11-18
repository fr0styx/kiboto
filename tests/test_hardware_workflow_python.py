"""The hardware runner's Python is /opt/kb-eval since the rename of 15 Nov; the nightly "Hardware
budgets" still called the path from before the rename and failed three nights running (exit code 127)."""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
EVAL_PY = "/opt/kb-eval/bin/python"


def test_the_hardware_workflow_uses_the_runners_python():
    text = (ROOT / ".github/workflows/hardware.yml").read_text(encoding="utf-8")
    used = set(re.findall(r"/opt/[\w.-]+/bin/python\w*", text))
    assert used == {EVAL_PY}


def test_the_scripts_say_the_same_path():
    text = (ROOT / "scripts/hardware_ai_eval.py").read_text(encoding="utf-8")
    assert EVAL_PY in text
