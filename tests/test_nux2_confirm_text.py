"""NUX-2: every action the server asks to confirm has its own translated dialog in the client."""

import re
from pathlib import Path

from backend.confirmations import ACTIONS

JS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "confirm-text.js"


def test_every_server_action_has_a_dialog():
    js = JS.read_text(encoding="utf-8")
    client = set(re.findall(r"^  '([a-z0-9_.]+)': \[", js, re.M))
    assert client == set(ACTIONS), (set(ACTIONS) - client, client - set(ACTIONS))


def test_targets_match():
    js = JS.read_text(encoding="utf-8")
    for action, summary in ACTIONS.items():
        # the whole entry: the formatter (oxfmt) may spread a long one over several lines
        start = js.index(f"  '{action}': [")
        entry = js[start : js.index("],", start)]
        assert ("{target}" in entry) == ("{target}" in summary), action
