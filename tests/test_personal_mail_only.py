"""A message meant for one person (their own alerts, something done to their account) goes to their
mail only: the household's ntfy topic and webhook got each person's alerts too."""

from backend.services import notifications as n

HOUSEHOLD = {
    "smtp_host": "mail.test",
    "smtp_port": 2525,
    "smtp_tls": False,
    "email_from": "kiboto@test.local",
    "email_enabled": True,
    "email_to": "owner@test.local",
    "ntfy_enabled": True,
    "ntfy_topic": "house",
    "webhook_enabled": True,
    "webhook_url": "https://hooks.test/x",
    "discord_enabled": True,
    "discord_webhook_url": "https://discord.test/api/webhooks/1/x",
    "apprise_urls": ["json://hooks.test/y"],
}


def test_mail_only_keeps_the_mail_settings_and_nothing_else():
    urls = n.build_apprise_urls(n.mail_only(HOUSEHOLD, "ana@test.local"))
    assert urls == ["mailto://mail.test:2525?to=ana%40test.local&from=kiboto%40test.local"]


def test_a_persons_alerts_and_account_notes_reach_only_their_mail(monkeypatch):
    sent = []
    monkeypatch.setattr(n, "_dispatch_apprise", lambda cfg, *a: sent.append(n.build_apprise_urls(cfg)) or True)
    monkeypatch.setattr(n, "_dispatch_ntfy", lambda *a: sent.append("ntfy") or True)
    monkeypatch.setattr(n, "get_routes", lambda: {"ana": {"email": "ana@test.local", "events": ["disk"]}})
    monkeypatch.setattr(n, "may_receive", lambda username, event: True)
    monkeypatch.setattr(n, "load_notification_config", lambda: dict(HOUSEHOLD))
    assert n._route_to_people(dict(HOUSEHOLD), "Disk", "warm", "warning", "disk") == ["ana"]
    assert n.notify_person("ana", "Password", "changed by an admin") is True
    mail = ["mailto://mail.test:2525?to=ana%40test.local&from=kiboto%40test.local"]
    assert sent == [mail, mail]
