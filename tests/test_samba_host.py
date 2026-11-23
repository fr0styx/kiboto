"""Samba as a service of the machine itself, on a machine set up for Kiboto.

Kiboto drove Samba only through a container: docker exec, and BusyBox's adduser, which Debian's
adduser refuses. On a managed host it now drives the machine's own smbd directly."""

import pytest

from backend.services import samba_engine, samba_host


class Tools:
    def __init__(self):
        self.ran = []
        self.answers = {}

    def __call__(self, cmd, feed=None, timeout=20):
        self.ran.append((cmd, feed))
        for start, answer in self.answers.items():
            if " ".join(cmd).startswith(start):
                return answer(cmd) if callable(answer) else answer
        return 0, "", ""

    def did(self, start):
        return [c for c, _ in self.ran if " ".join(c).startswith(start)]


@pytest.fixture
def tools():
    return Tools()


def test_the_machines_settings_file_points_at_kibotos(tmp_path):
    etc = tmp_path / "etc" / "samba" / "smb.conf"
    etc.parent.mkdir(parents=True)
    etc.write_text("[global]\n   workgroup = DEBIAN\n")
    conf = "/var/lib/kiboto/samba/smb.conf"
    assert samba_host.point_samba_here(conf, str(etc)) is True
    assert f"include = {conf}" in etc.read_text() and "config file" not in etc.read_text().split("[global]")[1]
    assert (etc.parent / "smb.conf.debian").read_text() == "[global]\n   workgroup = DEBIAN\n"  # Debian's own, kept
    assert samba_host.point_samba_here(conf, str(etc)) is False  # nothing to write the second time
    etc.write_text("someone edited it")
    assert samba_host.point_samba_here(conf, str(etc)) is True
    assert "workgroup = DEBIAN" in (etc.parent / "smb.conf.debian").read_text()  # the first copy stays
    fresh = tmp_path / "new" / "smb.conf"
    assert samba_host.point_samba_here(conf, str(fresh)) is True and fresh.exists()


def test_the_accounts_are_kept_in_kibotos_data_folder():
    lines = samba_host.global_lines("/var/lib/kiboto/samba")
    assert "   private dir = /var/lib/kiboto/samba/private" in lines


def test_each_person_is_a_user_of_the_machine_with_their_own_number(tools):
    tools.answers["id -u ana"] = (0, "20001", "")  # right already
    tools.answers["id -u ben"] = (0, "1001", "")  # an older one with another number
    tools.answers["id -u cleo"] = (1, "", "no such user")
    samba_host.ensure_accounts({"ana": 20001, "ben": 20002, "cleo": 20003}, tools)
    assert tools.did("userdel") == [["userdel", "ben"]]
    made = tools.did("useradd")
    assert [c[-1] for c in made] == ["ben", "cleo"]
    assert made[0] == ["useradd", "-M", "-N", "-u", "20002", "-g", "users", "-s", "/usr/sbin/nologin", "ben"]
    tools.answers["useradd"] = (4, "", "UID 20003 is not unique")
    samba_host.ensure_accounts({"cleo": 20003}, tools)  # said in the log, and the others go on


def test_a_change_closes_only_what_changed(tools):
    changed = {"shares": ["Films"], "ips": ["203.0.113.9"], "homes": False}
    assert samba_host.reload(changed, {}, tools) is True
    assert tools.did("smbcontrol") == [
        ["smbcontrol", "all", "reload-config"],
        ["smbcontrol", "all", "close-share", "Films"],
        ["smbcontrol", "all", "kill-client-ip", "203.0.113.9"],
    ]
    assert not tools.did("systemctl restart")


@pytest.mark.parametrize("changed", [None, {"shares": [], "ips": [], "homes": True}])
def test_what_cannot_be_reloaded_starts_the_server_again(tools, changed):
    assert samba_host.reload(changed, {}, tools) is True
    assert tools.did("systemctl restart") == [["systemctl", "restart", "smbd"]] and not tools.did("smbcontrol")


def test_a_server_that_is_down_is_started_and_a_failed_start_is_said(tools):
    tools.answers["systemctl is-active"] = (3, "", "")
    assert samba_host.reload({"shares": [], "ips": [], "homes": False}, {}, tools) is True
    assert tools.did("systemctl restart")
    tools.answers["systemctl restart"] = (1, "", "Job for smbd.service failed")
    assert samba_host.reload(None, {}, tools) is False
    tools.answers.clear()
    tools.answers["smbcontrol all reload-config"] = (1, "", "no smbd")  # a reload that fails falls back to a restart
    assert samba_host.reload({"shares": [], "ips": [], "homes": False}, {}, tools) is True
    assert tools.did("systemctl restart")


def test_passwords_and_switching_an_account(tools):
    tools.answers["id -u"] = (1, "", "")
    assert samba_host.set_password("Ana", 20001, "s3cret words", tools) is True
    cmd, feed = next((c, f) for c, f in tools.ran if c[0] == "smbpasswd")
    assert cmd == ["smbpasswd", "-s", "-a", "Ana"] and feed == "s3cret words\ns3cret words\n"
    assert tools.did("useradd")[0][-1] == "ana"  # the machine's user, lower case, before the password
    tools.answers["smbpasswd -s -a"] = (1, "", "Failed to add entry")
    assert samba_host.set_password("Ana", 20001, "x", tools) is False
    assert samba_host.set_enabled("Ana", False, tools) and tools.did("smbpasswd -d") == [["smbpasswd", "-d", "Ana"]]
    assert samba_host.set_enabled("Ana", True, tools) and tools.did("smbpasswd -e")
    assert samba_host.remove("Ana", tools) is True
    assert tools.did("smbpasswd -x") and tools.did("userdel")[-1] == ["userdel", "Ana"]


def test_the_runner_answers_for_a_missing_tool():
    assert samba_host.run(["true"]) == (0, "", "")
    assert samba_host.run(["no-such-tool-kb"])[0] == 127
    assert samba_host.run(["sleep", "5"], timeout=0.2)[0] == 124
    assert samba_host.run(["cat"], feed="in")[1] == "in"


# ---- the engine takes this road on a managed host, and only there


@pytest.fixture
def engine(tmp_path, monkeypatch, tools):
    monkeypatch.setattr(samba_engine, "SAMBA_DIR", str(tmp_path / "samba"))
    monkeypatch.setattr(samba_engine, "SAMBA_CONF_FILE", str(tmp_path / "samba" / "smb.conf"))
    monkeypatch.setattr(samba_engine, "SAMBA_SHARES_FILE", str(tmp_path / "samba" / "shares.json"))
    monkeypatch.setattr(samba_engine, "PASSDB_FILE", str(tmp_path / "samba" / "private" / "passdb.tdb"))
    monkeypatch.setattr(samba_engine, "PASSDB_SEEN_FILE", str(tmp_path / "samba" / "passdb.seen"))
    monkeypatch.setattr(samba_host, "active", lambda: True)
    monkeypatch.setattr(samba_host, "run", tools)
    seen = {}
    monkeypatch.setattr(
        samba_host, "point_samba_here", lambda conf, etc_conf="": seen.setdefault("conf", conf) and False
    )
    monkeypatch.setattr(samba_engine, "_people_names", lambda: {"ana"})
    monkeypatch.setattr("backend.services.smb_accounts.uid_of", lambda name: 20001)
    e = samba_engine.SambaEngine()
    return e, seen


def test_on_a_managed_host_the_engine_drives_the_machines_samba(engine, tools):
    e, seen = engine
    assert seen["conf"] == samba_engine.SAMBA_CONF_FILE  # pointed at Kiboto's settings when the engine starts
    conf = e.generate_and_save_conf()
    assert "private dir = " in conf and "passdb backend = tdbsam" in conf
    assert e.can_run_sidecar() == (False, "This machine serves files itself.")
    assert e.reload_service() is True
    assert seen["conf"] == samba_engine.SAMBA_CONF_FILE
    assert tools.did("useradd")[0][-1] == "ana" and (tools.did("systemctl restart") or tools.did("smbcontrol"))
    assert e.sync_samba_user("ana", "a long password") is True and tools.did("smbpasswd -s -a")
    assert e.sync_samba_user("ana") is False  # no password: nothing to set
    assert e.sync_samba_user("ana", delete=True) is True and tools.did("smbpasswd -x")
    assert e.set_account_enabled("ana", False) is True and tools.did("smbpasswd -d")
    st = e.get_status()
    assert (st.mode, st.native_samba_active, st.sidecar_status, st.running) == ("host_native", True, "not_needed", True)


def test_elsewhere_nothing_of_the_machine_is_touched(tmp_path, monkeypatch, tools):
    monkeypatch.setattr(samba_engine, "SAMBA_DIR", str(tmp_path / "samba"))
    monkeypatch.setattr(samba_engine, "SAMBA_CONF_FILE", str(tmp_path / "samba" / "smb.conf"))
    monkeypatch.setattr(samba_engine, "SAMBA_SHARES_FILE", str(tmp_path / "samba" / "shares.json"))
    monkeypatch.setattr(samba_host, "active", lambda: False)
    monkeypatch.setattr(samba_host, "run", tools)

    def never(*a, **k):
        raise AssertionError("the machine's Samba settings are not Kiboto's to write here")

    monkeypatch.setattr(samba_host, "point_samba_here", never)
    conf = samba_engine.SambaEngine().generate_and_save_conf()
    assert "private dir" not in conf and tools.ran == []


@pytest.mark.parametrize("name", ["-x", "--help", "a b", "ann/../root", ""])
def test_a_name_that_reads_as_an_option_reaches_no_account_tool(tools, name):
    samba_host.ensure_accounts({name: 20001}, tools)
    assert samba_host.set_password(name, 20001, "pw", tools) is False
    assert samba_host.remove(name, tools) is False
    assert samba_host.set_enabled(name, True, tools) is False
    assert tools.ran == []


def test_a_share_or_address_that_reads_as_an_option_is_not_passed_on(tools):
    assert samba_host.reload({"shares": ["-x", "media"], "ips": ["--help", "10.0.0.9"]}, {}, tools) is True
    assert tools.did("smbcontrol all close-share") == [["smbcontrol", "all", "close-share", "media"]]
    assert tools.did("smbcontrol all kill-client-ip") == [["smbcontrol", "all", "kill-client-ip", "10.0.0.9"]]
