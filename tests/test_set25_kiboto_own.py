"""SET-25 Apps 3b: Kiboto's own containers are marked, so the Apps window can leave them out."""

from backend import legacy_names
from backend.hardware import docker_stats
from backend.services import nas_name


def test_kiboto_itself_and_its_name_responder_are_its_own(monkeypatch):
    monkeypatch.setattr(docker_stats.socket, "gethostname", lambda: "abcdef123456")
    assert docker_stats.is_kiboto_own("abcdef123456789", "anything")  # this very container
    assert docker_stats.is_kiboto_own("ffff", "/kiboto")
    assert docker_stats.is_kiboto_own("ffff", "kiboto-name")
    assert docker_stats.is_kiboto_own("ffff", f"{legacy_names.OLD_NAS_NAME}-name")
    assert not docker_stats.is_kiboto_own("ffff", "jellyfin")
    assert not docker_stats.is_kiboto_own("ffff", "kiboto-ollama")  # an app a person can stop


def test_the_name_responder_name_is_the_one_nas_name_starts():
    assert docker_stats.NAME_RESPONDER == nas_name.CONTAINER
