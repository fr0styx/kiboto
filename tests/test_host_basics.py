"""The machine's own name and time zone follow Kiboto only on a machine set up for it."""

import os

import pytest

from backend import runtime
from backend.services import host_basics, identity, nas_name

HOSTS = "127.0.0.1\tlocalhost\n127.0.1.1\tdebian debian.lan\n\n# IPv6\n::1\tlocalhost ip6-localhost\n"


@pytest.fixture
def managed(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    assert runtime.managed_host()


class Calls:
    def __init__(self, answers=None):
        self.seen, self.answers = [], answers or {}

    def __call__(self, cmd, timeout=20):
        self.seen.append(cmd)
        for start, answer in self.answers.items():
            if " ".join(cmd).startswith(start):
                return answer
        return 0, ""


def test_the_own_name_line_is_replaced_and_everything_else_stays():
    out = host_basics.hosts_with_name(HOSTS, "attic")
    assert out == HOSTS.replace("127.0.1.1\tdebian debian.lan", "127.0.1.1\tattic")
    assert host_basics.hosts_with_name(out, "attic") == out


def test_a_hosts_file_without_the_line_gets_it_after_localhost():
    out = host_basics.hosts_with_name("127.0.0.1 localhost\n::1 localhost\n", "attic")
    assert out.splitlines() == ["127.0.0.1 localhost", "127.0.1.1\tattic", "::1 localhost"]
    assert host_basics.hosts_with_name("", "attic") == "127.0.1.1\tattic\n"


def test_a_guest_never_renames_its_host(tmp_path):
    do = Calls()
    assert host_basics.set_host_name("attic", do=do) is False
    assert host_basics.set_time_zone("Europe/Berlin", do=do) is False
    assert do.seen == []


def test_the_machine_takes_the_name(managed, tmp_path, monkeypatch):
    hosts = tmp_path / "hosts"
    hosts.write_text(HOSTS)
    monkeypatch.setattr(host_basics, "host_name", lambda: "debian")
    do = Calls()
    assert host_basics.set_host_name("attic", do=do, hosts=str(hosts)) is True
    assert do.seen == [["hostnamectl", "set-hostname", "attic"]]
    assert "127.0.1.1\tattic\n" in hosts.read_text()


def test_a_name_that_is_already_the_machines_changes_nothing(managed, tmp_path, monkeypatch):
    monkeypatch.setattr(host_basics, "host_name", lambda: "attic")
    do = Calls()
    assert host_basics.set_host_name("attic", do=do, hosts=str(tmp_path / "none")) is True
    assert do.seen == []


@pytest.mark.parametrize("name", ["", "-a", "a b", "a;reboot", "A" * 64, "Ünïcode"])
def test_a_name_that_is_not_a_host_name_reaches_no_command(managed, name):
    do = Calls()
    assert host_basics.set_host_name(name, do=do) is False
    assert do.seen == []


def test_a_refused_name_leaves_the_hosts_file(managed, tmp_path, monkeypatch):
    hosts = tmp_path / "hosts"
    hosts.write_text(HOSTS)
    monkeypatch.setattr(host_basics, "host_name", lambda: "debian")
    do = Calls({"hostnamectl": (1, "no")})
    assert host_basics.set_host_name("attic", do=do, hosts=str(hosts)) is False
    assert hosts.read_text() == HOSTS


def test_the_time_zone_is_read_from_the_link(tmp_path):
    zone = tmp_path / "usr" / "share" / "zoneinfo" / "Europe"
    zone.mkdir(parents=True)
    (zone / "Berlin").write_text("")
    link = tmp_path / "localtime"
    os.symlink(zone / "Berlin", link)
    assert host_basics.time_zone(str(link)) == "Europe/Berlin"
    assert host_basics.time_zone(str(tmp_path / "missing")) == ""


@pytest.mark.parametrize(
    "zone", ["", "Europe/../../etc", "x; reboot", "/etc/passwd", "a/b/c/d", "-h", "-Hx/y", "--help"]
)
def test_a_zone_that_is_not_a_zone_reaches_no_command(managed, zone):
    do = Calls()
    assert host_basics.set_time_zone(zone, do=do) is False
    assert do.seen == []


def test_the_machine_keeps_the_chosen_time(managed, monkeypatch):
    monkeypatch.setattr(host_basics, "time_zone", lambda: "Etc/UTC")
    do = Calls()
    assert host_basics.set_time_zone("America/Santo_Domingo", do=do) is True
    assert do.seen == [["timedatectl", "set-timezone", "America/Santo_Domingo"]]
    monkeypatch.setattr(host_basics, "time_zone", lambda: "America/Santo_Domingo")
    assert host_basics.set_time_zone("America/Santo_Domingo", do=Calls({"": (1, "")})) is True  # nothing to do


def test_choosing_a_zone_in_kiboto_sets_the_machines(managed, monkeypatch):
    asked = []
    monkeypatch.setattr(host_basics, "set_time_zone", lambda zone, do=None: asked.append(zone) or True)
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setattr(identity.time, "tzset", lambda: None, raising=False)  # this process keeps its own time
    assert identity.apply_timezone("Europe/Madrid") is True
    assert asked == ["Europe/Madrid"]
    assert identity.apply_timezone("Not/AZone") is False
    assert asked == ["Europe/Madrid"]


# --- the name service as a service of the machine ------------------------------------------------
@pytest.fixture
def name_service(managed, tmp_path, monkeypatch):
    monkeypatch.setattr(nas_name, "STATE_FILE", str(tmp_path / "nas_name.json"))
    monkeypatch.setattr(nas_name, "timemachine_shares", lambda: ["backups"])
    monkeypatch.setattr(nas_name, "serves_windows", lambda: True)
    monkeypatch.setattr(nas_name, "device_seed", lambda: "seed")
    monkeypatch.setattr(nas_name, "_docker", lambda *a, **k: pytest.fail("Docker is not asked on a managed host"))
    do = Calls({"systemctl is-active": (3, "inactive")})
    monkeypatch.setattr(host_basics, "run", do)
    named = []
    monkeypatch.setattr(host_basics, "set_host_name", lambda name, do=None: named.append(name) or True)
    return do, named


def test_a_machine_of_its_own_is_found_by_name_from_the_start(name_service):
    do, named = name_service
    assert nas_name.config()["enabled"] is True
    st = nas_name.ensure()
    assert st["running"] is True and st["address"] == "kiboto.local" and st["error"] == ""
    assert named == ["kiboto"]
    started = next(c for c in do.seen if c[0] == "systemd-run")
    assert started[started.index("--unit") + 1] == "kiboto-name.service"
    assert "DynamicUser=yes" in started and "ProtectSystem=strict" in started and "Restart=always" in started
    at = started.index("--names")
    assert started[at - 1].endswith("mdns_responder.py") and os.path.exists(started[at - 1])
    assert started[at:] == [
        "--names", "kiboto", "--label", "Kiboto", "--http-port", "8082", "--timemachine", "backups",
        "--windows", "--workgroup", "WORKGROUP", "--device", "seed",
    ]  # fmt: skip


def test_a_guest_stays_silent_until_asked(tmp_path, monkeypatch):
    monkeypatch.setattr(nas_name, "STATE_FILE", str(tmp_path / "nas_name.json"))
    assert nas_name.config()["enabled"] is False


def test_a_unit_that_already_matches_is_left_running(name_service, monkeypatch):
    do, _ = name_service
    cfg = nas_name.config()
    described = nas_name.service_command(cfg)
    described = described[described.index("--description") + 1]
    do.answers = {"systemctl is-active": (0, "active"), "systemctl show": (0, described)}
    assert nas_name.ensure()["running"] is True
    assert not [c for c in do.seen if c[0] == "systemd-run" or c[:2] == ["systemctl", "stop"]]


def test_a_rename_restarts_the_unit_with_both_names_and_renames_the_machine(name_service):
    do, named = name_service
    do.answers = {"systemctl is-active": (0, "active"), "systemctl show": (0, "Kiboto name service 0000")}
    st = nas_name.save(name="Attic.local")
    assert st["name"] == "attic" and st["also_answers"] == ["kiboto"]
    assert named == ["attic"]
    assert ["systemctl", "stop", "kiboto-name.service"] in do.seen
    started = next(c for c in do.seen if c[0] == "systemd-run")
    assert started[started.index("--names") + 1] == "attic,kiboto"


def test_turning_it_off_stops_the_unit_and_keeps_the_machines_name(name_service):
    do, named = name_service
    do.answers = {"systemctl is-active": (0, "active")}
    st = nas_name.save(enabled=False)
    assert st["enabled"] is False and st["running"] is False
    assert ["systemctl", "stop", "kiboto-name.service"] in do.seen
    assert named == [] and not [c for c in do.seen if c[0] == "systemd-run"]


def test_a_unit_that_does_not_start_is_said(name_service):
    do, _ = name_service
    do.answers = {"systemctl is-active": (3, "inactive"), "systemd-run": (1, "Failed to start")}
    st = nas_name.ensure()
    assert st["running"] is False and st["error"] == "The name service could not be started."
