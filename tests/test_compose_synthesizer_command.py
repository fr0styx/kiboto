"""A backup keeps what the container runs: its command and entrypoint (found restoring an app
backup on a real Docker engine, where the restored container ran its image's default and stopped)."""

import yaml

from backend.services.compose_synthesizer import format_compose_yaml, synthesize_compose_spec


def _inspect(**config):
    return {
        "Name": "/web",
        "Config": {"Image": "busybox:1.36", **config},
        "HostConfig": {"RestartPolicy": {"Name": "always"}},
    }


def test_command_and_entrypoint_are_kept_and_read_back_exactly():
    cmd = ["sh", "-c", "echo 'it''s' \"quoted\" && sleep 3600"]
    name, spec = synthesize_compose_spec(_inspect(Cmd=cmd, Entrypoint=["/init"]))
    assert spec["command"] == cmd and spec["entrypoint"] == ["/init"]
    back = yaml.safe_load(format_compose_yaml(name, spec))["services"][name]
    assert back["command"] == cmd and back["entrypoint"] == ["/init"]


def test_nothing_added_when_the_container_runs_its_image_default():
    _, spec = synthesize_compose_spec(_inspect(Cmd=None, Entrypoint=None))
    assert "command" not in spec and "entrypoint" not in spec
    _, spec = synthesize_compose_spec(_inspect(Cmd="sleep 10"))
    assert spec["command"] == "sleep 10"


def test_secrets_in_a_command_are_masked_when_asked():
    _, spec = synthesize_compose_spec(_inspect(Cmd=["redis-server", "--requirepass=hunter2secret"]), mask_secrets=True)
    assert "hunter2secret" not in " ".join(spec["command"])
