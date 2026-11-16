"""SET-23 (Settings decision 4): plain HTTP costs nothing on the home network and counts only when
the NAS is reachable from outside; the Overview, which has no request, says what the page said."""

import types

import pytest

from backend.services import security_advisor as sa


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(sa.config, "ENABLE_PROXY_SSO", False, raising=False)
    sa._outside.update(at=0.0, public=False)
    sa._last_https["seen"] = False
    yield


def _https_row(request=None):
    checks, issues = [], []
    sa._check_https(checks, issues, request)
    return checks[0], issues


def test_plain_http_at_home_is_a_suggestion(monkeypatch):
    monkeypatch.setattr(sa, "reachable_from_outside", lambda now=None: False)
    row, issues = _https_row()
    assert row["passed"] is False and row["penalty"] == 0 and row["variant"] == "home" and issues == []


def test_plain_http_reachable_from_outside_needs_a_look(monkeypatch):
    monkeypatch.setattr(sa, "reachable_from_outside", lambda now=None: True)
    row, issues = _https_row()
    assert row["penalty"] == 15 and row["severity"] == "medium" and "variant" not in row
    assert issues and issues[0]["id"] == "sec-issue-https-transport"


def test_the_overview_says_what_the_last_page_view_saw(monkeypatch):
    import backend.auth as auth

    monkeypatch.setattr(auth, "request_is_https", lambda r: True)
    monkeypatch.setattr(sa, "reachable_from_outside", lambda now=None: True)
    row, _ = _https_row(types.SimpleNamespace())
    assert row["passed"] is True
    row, _ = _https_row(None)  # the Overview: no request
    assert row["passed"] is True and row["penalty"] == 0


def test_reachable_from_outside_reads_exposure_once_a_minute(monkeypatch):
    from backend.services import exposure

    calls = []
    monkeypatch.setattr(exposure, "summary", lambda: calls.append(1) or {"level": "public"})
    assert sa.reachable_from_outside(now=1000.0) is True
    assert sa.reachable_from_outside(now=1030.0) is True and len(calls) == 1
    monkeypatch.setattr(exposure, "summary", lambda: {"level": "private"})
    assert sa.reachable_from_outside(now=1100.0) is False

    def broken():
        raise OSError("tailscale not answering")

    monkeypatch.setattr(exposure, "summary", broken)
    assert sa.reachable_from_outside(now=1200.0) is False
