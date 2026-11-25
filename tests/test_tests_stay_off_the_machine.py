"""The tests behave the same on every machine because they never reach the one they run on.

CI's Debian 13 job runs in a container that has the runner's Docker socket, as root. There
"Kiboto's own container" was the job's own container, and root's record of a network trial was
one real file every test worker shared. Both are given to each test by tests/conftest.py."""

import os

from backend import config
from backend.hardware.net import managed


def test_no_test_reaches_the_machines_docker():
    assert config.RAW_DOCKER_SOCK != "/var/run/docker.sock"
    assert config.docker_sock() == config.RAW_DOCKER_SOCK
    assert not os.path.exists(config.docker_sock())


def test_kibotos_own_container_is_not_found_through_a_real_socket(monkeypatch):
    """Even where a test says every path exists, as the update tests do."""
    from backend.api import system

    monkeypatch.setattr(os.path, "exists", lambda path: True)
    assert system._own_container_info() is None


def test_each_test_has_its_own_trial_record(tmp_path):
    assert managed.ROOT_STATE.startswith(str(tmp_path))
    assert not managed.ROOT_STATE.startswith("/var/lib/")
