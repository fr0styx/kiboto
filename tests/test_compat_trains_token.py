"""The nightly release-line check asks GitHub with the workflow's token: without one it shares the
runner's address limit and failed on 17 Nov with "403 rate limit exceeded"."""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _module():
    spec = importlib.util.spec_from_file_location("compat_trains", ROOT / "scripts/compat_trains.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Answer:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"[]"


def _seen(monkeypatch, mod, url):
    sent = []
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda req, timeout: sent.append(req) or _Answer())
    assert mod._get(url) == []
    return {k.lower(): v for k, v in sent[0].header_items()}


def test_github_is_asked_with_the_token(monkeypatch):
    mod = _module()
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    assert _seen(monkeypatch, mod, mod.TRUENAS_TAGS)["authorization"] == "Bearer t0ken"


def test_the_token_never_goes_elsewhere(monkeypatch):
    mod = _module()
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    assert "authorization" not in _seen(monkeypatch, mod, mod.UNRAID_FEED)


def test_without_a_token_it_still_asks(monkeypatch):
    mod = _module()
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert "authorization" not in _seen(monkeypatch, mod, mod.TRUENAS_TAGS)


def test_the_workflow_passes_the_token():
    text = (ROOT / ".github/workflows/compat.yml").read_text(encoding="utf-8")
    assert "GITHUB_TOKEN: ${{ github.token }}" in text
