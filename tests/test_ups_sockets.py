"""SET-31, Power stage 5: the UPS switches its sockets back on when the power returns (NUT
"shutdown.return"), and Kiboto reads the answer. Talks to a small fake upsd on the loopback."""

import socket
import threading

import pytest

from backend.services import ups_sockets as us


class FakeUpsd:
    """Answers NUT lines from a table; records what it was sent."""

    def __init__(self, answers):
        self.answers = answers
        self.seen = []
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        conn, _ = self.srv.accept()
        with conn:
            buf = b""
            while True:
                data = conn.recv(4096)
                if not data:
                    return
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode()
                    self.seen.append(text)
                    word = text.split()[0]
                    conn.sendall((self.answers.get(word, "ERR UNKNOWN-COMMAND") + "\n").encode())


def cfg(port, **kw):
    return {"mode": "nut_client", "host": "127.0.0.1", "port": port, "ups_name": "myups", **kw}


def test_shutdown_return_is_sent_and_its_answer_read():
    upsd = FakeUpsd({"USERNAME": "OK", "PASSWORD": "OK", "INSTCMD": "OK"})
    res = us.send_return(cfg(upsd.port, username="monuser", password="secret"))
    assert res["ok"] is True
    assert upsd.seen == ["USERNAME monuser", "PASSWORD secret", "INSTCMD myups shutdown.return"]


def test_a_refusal_is_said():
    upsd = FakeUpsd({"INSTCMD": "ERR ACCESS-DENIED"})
    res = us.send_return(cfg(upsd.port))
    assert res == {"ok": False, "code": "refused", "why": "The UPS refused: ERR ACCESS-DENIED"}


def test_a_wrong_password_stops_before_the_command():
    upsd = FakeUpsd({"USERNAME": "OK", "PASSWORD": "ERR INVALID-PASSWORD"})
    res = us.send_return(cfg(upsd.port, username="u", password="bad"))
    assert res["code"] == "unreachable" and "password" in res["why"]
    assert not any(line.startswith("INSTCMD") for line in upsd.seen)


@pytest.mark.parametrize(
    "listing,ok,code",
    [
        ("BEGIN LIST CMD myups\nCMD myups shutdown.return\nCMD myups test.battery.start\nEND LIST CMD myups", True, ""),
        ("BEGIN LIST CMD myups\nCMD myups load.off\nEND LIST CMD myups", False, "no_command"),
        ("ERR UNKNOWN-UPS", False, "refused"),
    ],
)
def test_check_lists_the_ups_commands(listing, ok, code):
    upsd = FakeUpsd({"LIST": listing})
    res = us.check(cfg(upsd.port))
    assert res["ok"] is ok and res["code"] == code


def test_not_over_nut_or_unreachable():
    assert us.check({"mode": "usb_hid"})["code"] == "not_nut"
    assert us.send_return({"mode": "apcupsd_client", "port": 3551})["code"] == "not_nut"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert us.check(cfg(port))["code"] == "unreachable"


def test_the_safe_shutdown_asks_for_shutdown_return(monkeypatch):
    from backend.services import ups_watchdog

    upsd = FakeUpsd({"INSTCMD": "OK"})
    monkeypatch.setattr(ups_watchdog, "load_ups_config", lambda: cfg(upsd.port))
    assert ups_watchdog.send_ups_cut_power()["ok"] is True
    assert upsd.seen == ["INSTCMD myups shutdown.return"]
    upsd2 = FakeUpsd({"INSTCMD": "ERR CMD-NOT-SUPPORTED"})
    monkeypatch.setattr(ups_watchdog, "load_ups_config", lambda: cfg(upsd2.port))
    assert ups_watchdog.send_ups_cut_power()["ok"] is False
