"""The held kernel, ZFS and Docker move only to the versions a Kiboto release was tested with."""

import json
import os

import pytest

from backend import runtime
from backend.services import host_set

TESTED = {
    "linux-image-amd64": "6.12.117-1",
    "linux-headers-amd64": "6.12.117-1",
    "zfs-dkms": "2.4.4-1~bpo13+1",
    "zfsutils-linux": "2.4.4-1~bpo13+1",
    "docker.io": "26.1.5+dfsg1-9+deb13u1+b1",
}


def debian_lt(a, b):
    """A small stand-in for dpkg --compare-versions, good for these versions."""

    def key(v):
        import re

        return [(0, int(x)) if x.isdigit() else (1 if x != "~" else -1, x) for x in re.findall(r"\d+|~|[a-z]+", v)]

    return key(a) < key(b)


class Machine:
    def __init__(self, installed, offered=None, available=None, kernels=("6.12.117+deb13-amd64",)):
        self.installed, self.offered = dict(installed), dict(offered or installed)
        self.available = {p: list(v) for p, v in (available or {}).items()}
        self.kernels, self.seen, self.refuse, self.unit = list(kernels), [], set(), False

    def __call__(self, cmd, timeout=60):
        self.seen.append(cmd)
        if cmd[0] in self.refuse:
            return 1, "E: refused"
        if cmd[0] == "dpkg-query":
            v = self.installed.get(cmd[-1], "")
            return (0, v) if v else (1, "")
        if cmd[:2] == ["apt-cache", "policy"]:
            return 0, f"{cmd[-1]}:\n  Installed: x\n  Candidate: {self.offered.get(cmd[-1], '(none)')}\n"
        if cmd[:2] == ["apt-cache", "madison"]:
            p = cmd[-1]
            versions = self.available.get(p) or [self.offered.get(p, "")]
            return 0, "\n".join(
                f" {p} | {v} | mirror trixie/main amd64 Packages" for v in versions if v
            ) + f"\n {p} | x | trixie Sources"
        if cmd[:2] == ["dpkg", "--compare-versions"]:
            return (0 if debian_lt(cmd[2], cmd[4]) else 1), ""
        if cmd[:2] == ["systemctl", "is-active"]:
            return (0 if self.unit else 3), ""
        if cmd[0] == "systemd-run":
            self.unit = True
        if cmd[:2] == ["apt-get", "install"]:
            for want in cmd[5:]:
                p, v = want.split("=", 1)
                self.installed[p] = v
        if cmd[:2] == ["dkms", "status"]:
            return 0, "\n".join(f"zfs/2.4.4, {k}, x86_64: installed" for k in self.kernels)
        return 0, ""


@pytest.fixture
def managed(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    monkeypatch.setattr(host_set, "DATA_DIR", str(tmp_path / "data"))
    os.makedirs(tmp_path / "data")
    monkeypatch.setattr(host_set, "tested_with", lambda root="": dict(TESTED))
    monkeypatch.setattr(host_set, "kernel_follows_debian", lambda: False)  # as before 2.0.7; see below
    monkeypatch.setattr(host_set, "REBOOT_FLAG", str(tmp_path / "reboot-required"))
    modules = tmp_path / "modules"
    monkeypatch.setattr(host_set, "MODULES", str(modules))

    def kernels(*names):
        for n in names:
            (modules / n / "kernel").mkdir(parents=True, exist_ok=True)

    kernels("6.12.117+deb13-amd64")
    return kernels


OLD_DOCKER = {**TESTED, "docker.io": "26.1.5+dfsg1-9+deb13u1"}


def test_this_release_says_what_it_was_tested_with(tmp_path):
    from pathlib import Path

    here = Path(__file__).resolve().parent.parent
    said = host_set.tested_with(str(here))
    assert set(said) == set(host_set.PACKAGES)
    (tmp_path / "packaging").mkdir()
    (tmp_path / "packaging" / "host-set.json").write_text(
        json.dumps({"tested_with": {"docker.io": "1; rm -rf /", "bash": "5"}})
    )
    assert host_set.tested_with(str(tmp_path)) == {}
    assert host_set.tested_with(str(tmp_path / "nowhere")) == {}


def test_a_guest_changes_nothing_on_its_host(tmp_path):
    m = Machine(TESTED)
    assert host_set.status(m) == {"managed": False}
    assert host_set.check(m) is False and host_set.start(m) is False
    assert m.seen == []


def test_as_tested_means_nothing_to_move(managed):
    st = host_set.status(Machine(TESTED))
    assert st["move"] == [] and st["waiting"] == [] and st["ahead"] == [] and st["tested"] is True
    assert [p["name"] for p in st["packages"]] == list(host_set.PACKAGES)


def test_an_older_docker_moves_to_the_tested_build(managed):
    m = Machine(OLD_DOCKER, offered=TESTED, available={"docker.io": [TESTED["docker.io"], OLD_DOCKER["docker.io"]]})
    assert host_set.status(m)["move"] == ["docker.io"]
    assert host_set.start(m) is True
    assert host_set.status(m)["running"] is True and host_set.start(m) is False  # one at a time
    result = host_set.apply(m)
    assert result["result"] == "moved" and result["moved"] == ["docker.io"]
    assert ["apt-mark", "unhold", "docker.io"] in m.seen
    assert ["apt-get", "install", "-y", "-qq", "--no-install-recommends", f"docker.io={TESTED['docker.io']}"] in m.seen
    assert m.seen.index(["apt-mark", "hold", *host_set.PACKAGES]) > m.seen.index(
        ["apt-get", "install", "-y", "-qq", "--no-install-recommends", f"docker.io={TESTED['docker.io']}"]
    )
    assert m.installed["docker.io"] == TESTED["docker.io"]


def test_a_tested_version_debian_keeps_beside_a_newer_one_is_still_taken(managed):
    # Debian offers the 7.3 backport and 6.12 at once; the tested 6.12 is on offer, not the default
    m = Machine(
        {**TESTED, "linux-image-amd64": "6.12.107-1"},
        offered={**TESTED, "linux-image-amd64": "7.3.4-1~bpo13+1"},
        available={"linux-image-amd64": ["7.3.4-1~bpo13+1", "6.12.117-1"]},
    )
    st = host_set.status(m)
    assert st["move"] == ["linux-image-amd64"] and st["waiting"] == ["linux-image-amd64"]


def test_a_newer_version_nobody_tested_waits(managed):
    m = Machine(TESTED, offered={**TESTED, "zfs-dkms": "2.4.5-1~bpo13+1"})
    st = host_set.status(m)
    assert st["move"] == [] and st["waiting"] == ["zfs-dkms"]


def test_a_tested_version_that_is_not_on_offer_is_not_asked_for(managed):
    m = Machine(OLD_DOCKER, offered=OLD_DOCKER)
    assert host_set.status(m)["move"] == []
    assert host_set.start(m) is False


def test_a_machine_ahead_of_the_tested_set_is_never_moved_back(managed):
    m = Machine({**TESTED, "docker.io": "27.0.0-1"}, available={"docker.io": ["27.0.0-1", TESTED["docker.io"]]})
    st = host_set.status(m)
    assert st["move"] == [] and st["ahead"] == ["docker.io"]


def test_a_failed_install_holds_everything_again_and_says_why(managed):
    m = Machine(OLD_DOCKER, offered=TESTED)
    m.refuse = {"apt-get"}
    result = host_set.apply(m)
    assert result["result"] == "failed" and result["error"] == "E: refused"
    assert ["apt-mark", "hold", *host_set.PACKAGES] in m.seen
    assert host_set.status(m)["last"]["result"] == "failed"


def test_a_new_kernel_without_zfs_is_said_before_anyone_restarts(managed):
    managed("7.3.4+bpo-amd64")
    m = Machine(
        {**TESTED, "linux-image-amd64": "6.12.107-1"},
        offered=TESTED,
        kernels=("6.12.117+deb13-amd64",),
    )
    result = host_set.apply(m)
    assert result["result"] == "zfs_missing" and "7.3.4+bpo-amd64" in result["error"]
    assert (
        host_set.zfs_built_for_every_kernel(Machine(TESTED, kernels=("6.12.117+deb13-amd64", "7.3.4+bpo-amd64"))) == []
    )


def test_nothing_to_move_is_recorded_as_nothing(managed):
    assert host_set.apply(Machine(TESTED))["result"] == "nothing"
    assert host_set.main(["x"]) == 2


def test_a_restart_that_finishes_a_kernel_is_said(managed, tmp_path):
    (tmp_path / "reboot-required").write_text("")
    assert host_set.status(Machine(TESTED))["restart_needed"] is True


def test_checking_asks_debian(managed):
    m = Machine(TESTED)
    assert host_set.check(m) is True and ["apt-get", "update", "-qq"] in m.seen
    m.refuse = {"apt-get"}
    assert host_set.check(m) is False


# --- the routes -----------------------------------------------------------------------------------
def test_a_guest_answers_that_these_belong_to_the_host(client, auth_headers):
    assert client.get("/api/system/host-set", headers=auth_headers).json() == {"managed": False}
    assert client.post("/api/system/host-set/check", headers=auth_headers).status_code == 404
    assert client.post("/api/system/host-set/apply", headers=auth_headers).status_code == 404


@pytest.mark.real_confirmations
def test_installing_the_tested_versions_is_asked_first(managed, client, auth_headers, monkeypatch):
    from backend.services import host_basics

    m = Machine(OLD_DOCKER, offered=TESTED)
    monkeypatch.setattr(host_set, "run", m)
    monkeypatch.setattr(host_basics, "host_name", lambda: "attic")
    assert client.get("/api/system/host-set", headers=auth_headers).json()["move"] == ["docker.io"]
    r = client.post("/api/system/host-set/apply", headers=auth_headers)
    assert r.status_code == 428 and r.json()["action"] == "system.host_set"
    token = client.post(
        "/api/confirmations", headers=auth_headers, json={"action": "system.host_set", "target": "attic"}
    ).json()["token"]
    r = client.post("/api/system/host-set/apply", headers={**auth_headers, "X-Confirm-Token": token})
    assert r.status_code == 200 and r.json()["running"] is True
    r = client.post("/api/system/host-set/apply", headers={**auth_headers, "X-Confirm-Token": token})
    assert r.status_code in (409, 428)


def test_checking_debian_through_the_page(managed, client, auth_headers, monkeypatch):
    m = Machine(TESTED)
    monkeypatch.setattr(host_set, "run", m)
    assert client.post("/api/system/host-set/check", headers=auth_headers).json()["move"] == []
    m.refuse = {"apt-get"}
    r = client.post("/api/system/host-set/check", headers=auth_headers)
    assert r.status_code == 502 and "package lists" in r.json()["detail"]


def test_with_debians_security_fixes_the_kernel_follows_debian(managed, monkeypatch):
    monkeypatch.setattr(host_set, "kernel_follows_debian", lambda: True)
    m = Machine(
        {**OLD_DOCKER, "linux-image-amd64": "6.12.107-1"},
        offered={**TESTED, "linux-image-amd64": "6.12.120-1"},
        available={"docker.io": [TESTED["docker.io"]], "linux-image-amd64": ["6.12.120-1", "6.12.117-1"]},
    )
    st = host_set.status(m)
    # no tested kernel is offered and no newer one waits: Debian's security fixes move it
    assert st["move"] == ["docker.io"] and st["waiting"] == []
    assert st["follows_debian"] == ["linux-image-amd64", "linux-headers-amd64"] and st["security"]["on"] is True
    host_set.apply(m)
    assert ["apt-mark", "hold", "zfs-dkms", "zfsutils-linux", "docker.io"] in m.seen  # the kernel is not held again


def test_the_kernel_follows_debian_unless_the_setting_says_no(monkeypatch):
    import dataclasses

    from backend import config

    assert host_set.kernel_follows_debian() is True and host_set.held() == ["zfs-dkms", "zfsutils-linux", "docker.io"]
    monkeypatch.setattr(config, "SETTINGS", dataclasses.replace(config.SETTINGS, security_updates=False))
    assert host_set.kernel_follows_debian() is False and host_set.held() == list(host_set.PACKAGES)
