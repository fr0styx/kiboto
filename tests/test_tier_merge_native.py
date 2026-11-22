"""Merged folders on a machine set up for Kiboto: mergerfs as a service of the machine."""

import pytest

from backend import runtime
from backend.services import host_basics, tier_merge

MERGE = {
    "path": "/mnt/storage/tank/films",
    "fast": "/mnt/storage/tank/.kiboto-tier/films",
    "slow": "/mnt/storage/media/.kiboto-tier/films",
}


@pytest.fixture
def machine(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    monkeypatch.setattr(tier_merge, "CONF_DIR", str(tmp_path / "merge"))
    monkeypatch.setattr(tier_merge, "_docker", lambda *a, **k: pytest.fail("no container on a machine of its own"))
    kept = [dict(MERGE)]
    monkeypatch.setattr(tier_merge, "merges", lambda: kept)
    seen, unit = [], {"on": False, "described": ""}

    def run(cmd, timeout=20):
        seen.append(cmd)
        if cmd[:2] == ["systemctl", "is-active"]:
            return (0, "active") if unit["on"] else (3, "inactive")
        if cmd[:2] == ["systemctl", "show"]:
            return 0, unit["described"]
        if cmd[0] == "systemd-run":
            unit["on"], unit["described"] = True, cmd[cmd.index("--description") + 1]
        if cmd[:2] == ["systemctl", "stop"]:
            unit["on"] = False
        return 0, ""

    monkeypatch.setattr(host_basics, "run", run)
    return kept, seen, unit


def test_the_merges_run_as_a_service_of_the_machine(machine, tmp_path):
    kept, seen, unit = machine
    assert tier_merge.ensure() == ""
    started = next(c for c in seen if c[0] == "systemd-run")
    assert started[started.index("--unit") + 1] == "kiboto-merge" and started[-2:] == [
        "sh",
        str(tmp_path / "merge" / "merge.sh"),
    ]
    script = (tmp_path / "merge" / "merge.sh").read_text()
    assert (
        "merge /mnt/storage/tank/.kiboto-tier/films /mnt/storage/media/.kiboto-tier/films /mnt/storage/tank/films"
        in script
    )


def test_unchanged_merges_are_left_mounted_and_none_stops_the_unit(machine):
    kept, seen, unit = machine
    tier_merge.ensure()
    seen.clear()
    assert tier_merge.ensure() == "" and not [c for c in seen if c[0] == "systemd-run"]
    kept.clear()
    assert tier_merge.ensure() == "" and unit["on"] is False


def test_a_unit_that_does_not_start_is_said(machine, monkeypatch):
    monkeypatch.setattr(host_basics, "run", lambda cmd, timeout=20: (1, "no") if cmd[0] == "systemd-run" else (3, ""))
    assert tier_merge.ensure() == "no_start"


def test_a_machine_of_its_own_needs_no_container_to_offer_a_merge(machine, monkeypatch, tmp_path):
    monkeypatch.setattr(tier_merge.shutil, "which", lambda tool: "/usr/bin/mergerfs")
    fuse = tmp_path / "fuse"
    fuse.write_text("")
    monkeypatch.setattr(tier_merge, "FUSE", str(fuse))
    monkeypatch.setattr(tier_merge, "receives_mounts", lambda path: True)
    monkeypatch.setattr(tier_merge, "_engine", lambda: pytest.fail("no app engine is asked"))
    assert tier_merge.missing("/mnt/storage/tank/films") == ""
