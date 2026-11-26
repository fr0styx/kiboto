"""Kiboto 2.2 stops publishing the image's old name: About says when the container still uses it."""

from backend import legacy_names, runtime
from backend.api import system


def test_a_container_started_from_the_old_name_is_told(monkeypatch):
    monkeypatch.setattr(runtime, "in_container", lambda: True)
    monkeypatch.setattr(
        system,
        "_own_container_info",
        lambda: {"Config": {"Image": "ghcr.io/" + legacy_names.OLD_IMAGE_REPO + ":latest"}},
    )
    assert system._old_image_name() == "ghcr.io/" + legacy_names.OLD_IMAGE_REPO
    monkeypatch.setattr(system, "_own_container_info", lambda: {"Config": {"Image": "ghcr.io/fr0styx/kiboto:latest"}})
    assert system._old_image_name() == ""
    monkeypatch.setattr(system, "_own_container_info", lambda: None)
    assert system._old_image_name() == ""


def test_a_machine_of_its_own_has_no_image_name(monkeypatch):
    monkeypatch.setattr(runtime, "in_container", lambda: False)
    monkeypatch.setattr(system, "_own_container_info", lambda: (_ for _ in ()).throw(AssertionError("no Docker asked")))
    assert system._old_image_name() == ""
