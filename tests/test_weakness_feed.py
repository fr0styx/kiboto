"""The known-weakness feed for apps (owner, 19 Nov 2026): off by default; the comparison is local."""

import httpx
import pytest

from backend import outside_checks
from backend.services import security_advisor, weakness_feed

FEED = {
    "vulnerabilities": [
        {
            "cveID": "CVE-2026-1111",
            "vendorProject": "Grafana Labs",
            "product": "Grafana",
            "dateAdded": "2026-10-01",
            "knownRansomwareCampaignUse": "Unknown",
        },
        {
            "cveID": "CVE-2025-2222",
            "vendorProject": "Grafana Labs",
            "product": "Grafana",
            "dateAdded": "2025-03-01",
            "knownRansomwareCampaignUse": "Known",
        },
        {"cveID": "CVE-2026-3333", "vendorProject": "Plex", "product": "Plex Media Server", "dateAdded": "2026-09-15"},
        {"cveID": "CVE-2026-4444", "vendorProject": "Microsoft", "product": "Windows", "dateAdded": "2026-11-01"},
        {"cveID": "CVE-2026-5555", "vendorProject": "X", "product": "Go", "dateAdded": "2026-11-01"},
        {"cveID": "", "vendorProject": "No", "product": "Identifier", "dateAdded": "2026-11-01"},
        {"cveID": "CVE-2026-6666", "vendorProject": "Bad", "product": "Dates", "dateAdded": "soon"},
    ]
}
OCT = 1790812800.0  # 2026-10-01


@pytest.fixture(autouse=True)
def fresh_state(tmp_path, monkeypatch):
    monkeypatch.setattr(outside_checks, "STATE_FILE", str(tmp_path / "outside_checks.json"))
    monkeypatch.setattr(weakness_feed, "STATE_FILE", str(tmp_path / "weakness_feed.json"))


def test_the_list_is_cut_down_to_names_and_days():
    rows = weakness_feed.compact(FEED)
    by = {r["cve"]: r for r in rows}
    assert by["CVE-2026-1111"]["keys"] == ["grafana"] and by["CVE-2026-1111"]["product"] == "Grafana Labs Grafana"
    assert by["CVE-2026-3333"]["keys"] == ["plex", "plexmediaserver"]
    assert by["CVE-2025-2222"]["ransomware"] is True
    assert "CVE-2026-5555" not in by  # a two-letter name would match too much
    assert by["CVE-2026-6666"]["added"] == 0.0
    assert len(rows) == 5 and weakness_feed.compact({}) == []


def test_a_first_word_only_counts_when_it_is_the_makers_name():
    """Found on a real NAS: "Backup Exec" (Veritas) made every image called "backup" a match."""
    rows = weakness_feed.compact(
        {
            "vulnerabilities": [
                {"cveID": "CVE-1", "vendorProject": "Veritas", "product": "Backup Exec", "dateAdded": "2026-01-01"},
                {
                    "cveID": "CVE-2",
                    "vendorProject": "Roundcube",
                    "product": "Roundcube Webmail",
                    "dateAdded": "2026-01-01",
                },
                {"cveID": "CVE-3", "vendorProject": "Gitea", "product": "Gitea", "dateAdded": "2026-01-01"},
            ]
        }
    )
    by = {r["cve"]: r["keys"] for r in rows}
    assert by == {"CVE-1": ["backupexec"], "CVE-2": ["roundcube", "roundcubewebmail"], "CVE-3": ["gitea"]}
    apps = [
        {"name": "nightly", "image": "me/backup:1", "built": 1},
        {"name": "mail", "image": "roundcube/roundcubemail", "built": 1},
    ]
    assert weakness_feed.matches(apps, rows) == []  # "backup" is no product; "roundcubemail" is not its listed name
    assert [f["app"] for f in weakness_feed.matches([{"name": "git", "image": "gitea/gitea:1", "built": 1}], rows)] == [
        "git"
    ]


def test_an_app_is_named_by_its_image():
    assert weakness_feed.image_name("lscr.io/linuxserver/plex:latest") == "plex"
    assert weakness_feed.image_name("grafana/grafana@sha256:abc") == "grafana"
    assert weakness_feed.image_name("ghcr.io/home-assistant/home-assistant:stable") == "homeassistant"
    assert weakness_feed.image_name("") == ""


def test_only_a_copy_built_before_the_warning_is_flagged():
    entries = weakness_feed.compact(FEED)
    apps = [
        {"name": "grafana", "image": "grafana/grafana:latest", "built": OCT - 30 * 86400},  # older than the warning
        {"name": "plex", "image": "lscr.io/linuxserver/plex:latest", "built": OCT + 30 * 86400},  # built after: fixed
        {"name": "notes", "image": "neosmemo/memos:stable", "built": 0},
    ]
    found = weakness_feed.matches(apps, entries)
    assert [f["app"] for f in found] == ["grafana"]
    assert found[0]["cve"] == "CVE-2026-1111" and found[0]["count"] == 1 and found[0]["ransomware"] is False
    very_old = weakness_feed.matches([{"name": "g", "image": "grafana/grafana", "built": 1}], entries)
    assert very_old[0]["count"] == 2 and very_old[0]["ransomware"] is True and very_old[0]["cve"] == "CVE-2026-1111"


def test_off_by_default_nothing_is_downloaded_and_nothing_is_flagged():
    def never():
        raise AssertionError("downloaded while the check is off")

    assert weakness_feed.refresh(fetch=never) is None
    assert weakness_feed.due(10**10) is False and weakness_feed.findings() == []


def test_on_it_downloads_once_a_day_and_keeps_the_old_copy_when_the_site_is_down(monkeypatch):
    outside_checks.set_enabled("weakness_feed", True)
    assert weakness_feed.due(1000.0 + weakness_feed.EVERY_SECS) is True
    assert weakness_feed.refresh(now=1000.0, fetch=lambda: FEED) == 5
    assert weakness_feed.due(1000.0 + 3600) is False and weakness_feed.due(1000.0 + weakness_feed.EVERY_SECS) is True

    def down():
        raise httpx.ConnectError("no route")

    assert weakness_feed.refresh(now=2000.0, fetch=down) is None
    assert weakness_feed.stored()["fetched_at"] == 1000.0 and len(weakness_feed.stored()["entries"]) == 5
    monkeypatch.setattr(
        weakness_feed, "installed_apps", lambda: [{"name": "grafana", "image": "grafana/grafana", "built": 1}]
    )
    assert [f["app"] for f in weakness_feed.findings()] == ["grafana"]


def test_the_real_fetch_and_the_installed_apps(monkeypatch):
    seen = {}

    class Res:
        def raise_for_status(self):
            seen["checked"] = True

        def json(self):
            return FEED

    monkeypatch.setattr(httpx, "get", lambda url, **kw: seen.update(url=url, **kw) or Res())
    assert weakness_feed._fetch() == FEED and seen["url"] == weakness_feed.FEED_URL and seen["checked"]

    from backend.services import docker_client

    def docker(method, path, **kw):
        if path.startswith("/containers/json"):
            return 200, [
                {"Names": ["/grafana"], "Image": "grafana/grafana:latest", "ImageID": "sha256:aaa"},
                {"Names": ["/grafana2"], "Image": "grafana/grafana:latest", "ImageID": "sha256:aaa"},
                {"Names": [], "Image": "x/y", "ImageID": "sha256:bbb"},
            ]
        if path == "/images/sha256:aaa/json":
            return 200, {"Created": "2026-08-01T10:00:00.123456789Z"}
        return 404, {"message": "no such image"}

    monkeypatch.setattr(docker_client, "request", docker)
    apps = weakness_feed.installed_apps()
    assert [a["name"] for a in apps] == ["grafana", "grafana2", "sha256:bbb"[:12]]
    assert apps[0]["built"] == apps[1]["built"] > 0 and apps[2]["built"] == 0.0
    monkeypatch.setattr(docker_client, "request", lambda *a, **k: (500, {"message": "busy"}))
    assert weakness_feed.installed_apps() == []

    def gone(*a, **k):
        raise docker_client.DockerUnavailable(503, "no socket", "/containers/json")

    monkeypatch.setattr(docker_client, "request", gone)
    assert weakness_feed.installed_apps() == []
    assert weakness_feed._built("not a date") == 0.0


def test_the_security_page_names_the_apps_only_when_the_check_is_on(monkeypatch):
    monkeypatch.setattr(
        weakness_feed,
        "findings",
        lambda: [
            {
                "app": "grafana",
                "cve": "CVE-2026-1111",
                "product": "Grafana Labs Grafana",
                "added": OCT,
                "ransomware": False,
                "count": 1,
            }
        ],
    )
    checks, issues = [], []
    security_advisor._check_app_weaknesses(checks, issues)
    assert checks == [] and issues == []  # off: the Security page does not mention it
    outside_checks.set_enabled("weakness_feed", True)
    security_advisor._check_app_weaknesses(checks, issues)
    assert checks[0]["id"] == "app_weaknesses" and checks[0]["passed"] is False and checks[0]["penalty"] == 15
    assert checks[0]["params"] == {"apps": "grafana (CVE-2026-1111)", "count": 1}
    assert issues[0]["id"] == "sec-issue-app-weaknesses" and "grafana" in issues[0]["description"]
    monkeypatch.setattr(weakness_feed, "findings", lambda: [])
    checks, issues = [], []
    security_advisor._check_app_weaknesses(checks, issues)
    assert checks[0]["passed"] is True and checks[0]["penalty"] == 0 and issues == []


def test_a_newly_flagged_app_is_announced_once(monkeypatch):
    outside_checks.set_enabled("weakness_feed", True)
    monkeypatch.setattr(
        weakness_feed, "installed_apps", lambda: [{"name": "grafana", "image": "grafana/grafana", "built": 1}]
    )
    sent = []
    send = lambda title, message, **kw: sent.append((title, message, kw))  # noqa: E731
    from backend.services import notifications

    monkeypatch.setattr(notifications, "send_notification", send)
    assert weakness_feed.refresh(now=1000.0, fetch=lambda: FEED) == 5  # the download announces by itself
    assert len(sent) == 1
    title, message, kw = sent[0]
    assert title == "An app has a weakness that is being attacked"
    assert "grafana (CVE-2026-1111)" in message and kw["event_type"] == "security" and kw["level"] == "warning"
    assert kw["text"] == {
        "title_key": "alert.weakness.title",
        "msg_key": "alert.weakness.msg",
        "params": {"apps": "grafana (CVE-2026-1111)"},
    }
    # the next day's download says nothing new; the list and what was told are both kept
    assert weakness_feed.refresh(now=1000.0 + weakness_feed.EVERY_SECS, fetch=lambda: FEED) == 5
    assert len(sent) == 1 and weakness_feed.stored()["told"] == ["grafana:CVE-2026-1111"]
    assert weakness_feed.tell_about_new(send=send) == []
    # another app that turns up later is announced on its own
    monkeypatch.setattr(
        weakness_feed,
        "installed_apps",
        lambda: [
            {"name": "grafana", "image": "grafana/grafana", "built": 1},
            {"name": "plex", "image": "lscr.io/linuxserver/plex", "built": 1},
        ],
    )
    assert weakness_feed.tell_about_new(send=send) == ["plex"]
    assert "plex (CVE-2026-3333)" in sent[-1][1] and "grafana" not in sent[-1][1]


def test_nothing_flagged_nothing_announced(monkeypatch):
    outside_checks.set_enabled("weakness_feed", True)
    monkeypatch.setattr(weakness_feed, "installed_apps", lambda: [])

    def never(*a, **k):
        raise AssertionError("announced without a finding")

    assert weakness_feed.refresh(now=1000.0, fetch=lambda: FEED) == 5
    assert weakness_feed.tell_about_new(send=never) == []
