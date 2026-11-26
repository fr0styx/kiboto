"""Kiboto OS stays on Debian 13 (release review, OS platform finding 8): a move to Debian 14 would
change Python under the app, the root service and the updater at once. The apt rule that keeps the
machine there was tried on the test machine with Debian testing added as a source: Debian 13's own
packages kept installing, every package of the other release got priority -1, a full upgrade did
nothing, and backports kept their priority of 100."""

import os
import re
import shutil
import subprocess

import pytest

from backend.services import native_update as nu

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIN = os.path.join(ROOT, "packaging", "kiboto-debian13.pref")
INSTALL = os.path.join(ROOT, "packaging", "install.sh")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_the_rule_lets_debian_13_in_first_and_every_other_debian_release_not():
    records = [r for r in _read(PIN).strip().split("\n\n")]
    rules = [
        {k: v.strip() for k, v in (line.split(":", 1) for line in r.splitlines() if not line.startswith("Explanation"))}
        for r in records
    ]
    # apt takes the first rule that matches, so the order is the rule (found on the test machine)
    assert rules == [
        {"Package": "*", "Pin": "release o=Debian, n=/^trixie(-.*)?$/", "Pin-Priority": "500"},
        {"Package": "*", "Pin": "release o=Debian", "Pin-Priority": "-1"},
    ]
    assert "KIBOTO_KEEP_DEBIAN=0" in _read(PIN)


@pytest.mark.parametrize(
    "codename, kept",
    [
        ("trixie", True),
        ("trixie-security", True),
        ("trixie-updates", True),
        ("forky", False),
        ("sid", False),
        ("trixiex", False),
    ],
)
def test_which_releases_the_first_rule_names(codename, kept):
    pattern = re.search(r"n=/(.+)/$", _read(PIN).splitlines()[7].strip()).group(1)
    assert bool(re.fullmatch(pattern, codename)) is kept


def test_the_installer_writes_the_same_file():
    text = _read(INSTALL)
    body = text[text.index("<<'PIN'\n") + len("<<'PIN'\n") : text.index("\nPIN\n")] + "\n"
    assert body == _read(PIN)
    for branch in ("--from)", '--image | "")'):
        part = text[text.index(branch) :]
        part = part[: part.index(";;")]
        assert part.index("stay_on_debian13") < part.index("packages")  # before anything is installed


@pytest.mark.skipif(not shutil.which("sh"), reason="no shell")
def test_the_installers_function_writes_it(tmp_path):
    text = _read(INSTALL)
    fn = text[text.index("stay_on_debian13() {") : text.index("\n}\n", text.index("stay_on_debian13() {")) + 3]
    fn = fn.replace("/etc/apt/preferences.d", str(tmp_path / "prefs"))
    done = subprocess.run(["sh", "-c", fn + "\nstay_on_debian13"], capture_output=True, text=True, check=False)  # noqa: S603,S607
    assert done.returncode == 0, done.stderr
    written = tmp_path / "prefs" / "kiboto-debian13.pref"
    assert written.read_text() == _read(PIN) and oct(written.stat().st_mode & 0o777) == "0o644"


def _keep(monkeypatch, on):
    import dataclasses

    from backend import config

    monkeypatch.setattr(config, "SETTINGS", dataclasses.replace(config.SETTINGS, keep_debian=on))


@pytest.fixture
def machine(tmp_path, monkeypatch):
    rel = tmp_path / "rel"
    (rel / "packaging").mkdir(parents=True)
    shutil.copy(PIN, rel / "packaging" / "kiboto-debian13.pref")
    prefs = tmp_path / "prefs"
    prefs.mkdir()
    _keep(monkeypatch, True)
    return str(rel), str(prefs / "kiboto-debian13.pref")


def test_kiboto_puts_it_back_at_start_and_leaves_it_when_it_is_right(machine):
    rel, path = machine
    assert nu.keep_debian(rel, path) == "written"
    assert _read(path) == _read(PIN) and oct(os.stat(path).st_mode & 0o777) == "0o644"
    assert nu.keep_debian(rel, path) == "kept"
    with open(path, "w", encoding="utf-8") as f:
        f.write("Package: *\nPin: release o=Debian\nPin-Priority: 990\n")  # changed by hand
    assert nu.keep_debian(rel, path) == "written" and _read(path) == _read(PIN)


def test_told_to_let_apt_move_the_machine_it_takes_the_file_away(machine, monkeypatch):
    rel, path = machine
    nu.keep_debian(rel, path)
    _keep(monkeypatch, False)
    assert nu.keep_debian(rel, path) == "removed" and not os.path.exists(path)
    assert nu.keep_debian(rel, path) == ""


def test_nothing_is_done_without_apt_or_without_the_file_in_the_version(machine, tmp_path):
    rel, path = machine
    assert nu.keep_debian(rel, str(tmp_path / "no-apt" / "x.pref")) == ""
    os.remove(os.path.join(rel, "packaging", "kiboto-debian13.pref"))  # a version from before
    assert nu.keep_debian(rel, path) == "" and not os.path.exists(path)


def test_the_root_service_keeps_it_before_it_installs_anything(monkeypatch):
    from backend.services import host_door

    order = []
    monkeypatch.setattr(nu, "keep_debian", lambda rel: order.append("pin"))
    monkeypatch.setattr(nu, "add_missing_tools", lambda rel: order.append("packages") or [])
    assert host_door.handle({"op": "packages.add_missing", "args": {}}, 0)["ok"] is True
    assert order == ["pin", "packages"]


def test_no_test_reaches_this_machines_apt():
    assert not nu.APT_PIN.startswith("/etc/")
