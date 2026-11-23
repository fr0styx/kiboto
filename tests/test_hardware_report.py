"""scripts/hardware_report.sh: what a machine is made of, read-only and shareable."""

import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "hardware_report.sh")


def _text():
    with open(SCRIPT, encoding="utf-8") as f:
        return f.read()


def test_it_only_reads():
    code = "\n".join(line.split("#", 1)[0] for line in _text().splitlines())
    for word in (
        "mount ",
        "mkfs",
        "dd ",
        "hdparm",
        "smartctl",
        "apt",
        "curl",
        "wget",
        "rm ",
        "> /",
        "tee ",
        "modprobe",
    ):
        assert word not in code, word
    assert "-o NAME,MODEL,SIZE,TRAN,ROTA,TYPE" in code and "SERIAL" not in code  # no serial numbers
    assert not re.search(r"address\b(?!es)", code.replace("no addresses", ""))  # no MAC addresses read


@pytest.mark.skipif(not shutil.which("sh"), reason="no shell")
def test_it_runs_and_names_its_sections():
    done = subprocess.run(["sh", SCRIPT], capture_output=True, text=True, timeout=60, check=False)  # noqa: S603,S607
    assert done.returncode == 0, done.stderr
    for section in (
        "== System",
        "== Drives (no serial numbers)",
        "== Fans and temperatures (hwmon)",
        "== Graphics and AI chip",
    ):
        assert section in done.stdout
