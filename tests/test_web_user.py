"""ADR 0006 step 9: Kiboto's web process as the user kiboto, turned on by root only."""

import os

from backend.services import host_door, web_user


def _runner(answers=None):
    ran = []

    def do(cmd, timeout=600):
        ran.append(cmd)
        return (answers or {}).get(cmd[0], (0, ""))

    return ran, do


def test_turning_it_on_makes_the_user_and_the_drop_in(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "door-audit.log").write_text("")
    homes = tmp_path / "homes"
    homes.mkdir()
    monkeypatch.setattr(web_user, "_homes", lambda: str(homes))
    drop_in = tmp_path / "kiboto.service.d" / "web-user.conf"
    ran, do = _runner({"id": (1, "no such user")})
    assert web_user.turn_on(do, str(drop_in), str(data)) == []
    text = drop_in.read_text()
    assert "User=kiboto" in text and "NoNewPrivileges=yes" in text and "SupplementaryGroups=users dialout" in text
    assert "CapabilityBoundingSet=CAP_NET_BIND_SERVICE" in text
    names = [c[0] for c in ran]
    assert names.index("useradd") < names.index("chown") < names.index("setfacl")
    assert ["chown", "root:root", str(data / "door-audit.log")] in ran  # what root wrote stays root's
    assert ["setfacl", "-R", "-m", "-d", "u:kiboto:rwX", str(homes)] in ran
    assert ran[-1] == ["systemctl", "daemon-reload"]
    assert web_user.is_on(str(drop_in)) and web_user.status(str(drop_in)) == {"on": True, "user": "kiboto"}

    ran, do = _runner()
    assert web_user.turn_off(do, str(drop_in)) == [] and not drop_in.exists()
    assert ran == [["systemctl", "daemon-reload"]]
    assert web_user.turn_off(do, str(drop_in)) == []


def test_what_could_not_be_done_is_said(tmp_path, monkeypatch):
    monkeypatch.setattr(web_user, "_homes", lambda: "")
    ran, do = _runner({"id": (1, ""), "useradd": (9, "useradd: cannot lock /etc/passwd")})
    problems = web_user.turn_on(do, str(tmp_path / "d.conf"), str(tmp_path))
    assert problems and "could not be made" in problems[0] and not (tmp_path / "d.conf").exists()
    ran, do = _runner({"chown": (1, "")})
    problems = web_user.turn_on(do, str(tmp_path / "d.conf"), str(tmp_path))
    assert any("was not given" in p for p in problems)


def test_the_command_line(monkeypatch, capsys):
    monkeypatch.setattr(web_user, "turn_on", lambda: [])
    monkeypatch.setattr(web_user, "turn_off", lambda: ["x"])
    monkeypatch.setattr(web_user, "status", lambda: {"on": False})
    assert web_user.main(["", "on"]) == 0 and web_user.main(["", "off"]) == 1
    assert web_user.main(["", "status"]) == 0 and web_user.main(["", "what"]) == 2
    assert "restart Kiboto" in capsys.readouterr().out


def test_no_door_operation_can_give_root_back():
    assert not [op for op in host_door.OPERATIONS if "web_user" in op or "run_as" in op]


def test_the_door_lets_in_a_web_user_made_after_it_started(monkeypatch, tmp_path):
    import socket

    monkeypatch.setattr(host_door, "AUDIT", str(tmp_path / "door-audit.log"))

    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    me = os.getuid()
    monkeypatch.setattr(host_door, "peer_uid", lambda conn: me)
    monkeypatch.setattr(host_door, "allowed_uids", lambda: {0, me})
    b.sendall(b'{"op": "door.ping", "args": {}}\n')
    host_door._serve_one(a, {0})
    assert b'"pong"' in b.recv(4096)
    b.close()
