"""A first start of the install image that stopped part way can run again: the Samba it installed
itself is not taken for a machine someone else set up (found by the ISO run of the OS audit)."""

import os
import subprocess
from pathlib import Path

INSTALL = Path(__file__).resolve().parents[1] / "packaging" / "install.sh"
TEXT = INSTALL.read_text(encoding="utf-8")


def _fn(name: str) -> str:
    start = TEXT.index(name + "() {")
    return TEXT[start : TEXT.index("\n}\n", start) + 3]


def _fresh(etc) -> str:
    script = (
        'die() { echo "die: $*"; exit 1; }\nETC='
        + str(etc)
        + "\n"
        + _fn("must_be_fresh")
        + "\nmust_be_fresh && echo fresh\n"
    )
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=dict(os.environ)).stdout.strip()


def test_a_started_install_is_let_through_before_any_check(tmp_path):
    (tmp_path / "install-started").write_text("")
    assert _fresh(tmp_path) == "fresh"


def test_the_mark_comes_after_the_check_and_goes_when_kiboto_runs():
    for branch in ("--from)", '--image | "")'):
        part = TEXT[TEXT.index(branch) :]
        part = part[: part.index(";;")]
        assert part.index("must_be_fresh; mark_started") < part.index("packages")
        assert part.rstrip().endswith('rm -f "$ETC/install-started"')


def test_what_it_installs_is_readable_by_kiboto_whatever_umask_called_it():
    head = TEXT[: TEXT.index("say() {")]
    assert "\numask 022\n" in head
