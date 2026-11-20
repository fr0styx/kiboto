"""High availability: the second NAS keeps a copy of the first one's people and settings (the
owner's decision of 19 Nov 2026: applied only at takeover). Two boxes are played by one process,
as in test_ha_link.py; the backup travels in sealed pieces over the link."""

import copy
import io
import json
import os
import time
import zipfile

import pytest

from backend.services import ha_link as ha
from backend.services import ha_state as hs

A, B = "http://192.168.1.10:8082", "http://192.168.1.20:8082"


class Net:
    def __init__(self, tmp_path, monkeypatch):
        self.dirs = {A: tmp_path / "first", B: tmp_path / "second"}
        for d in self.dirs.values():
            d.mkdir()
        self.patch, self.me, self.tamper, self.asked = monkeypatch, A, None, []
        monkeypatch.setattr(ha, "my_name", lambda: "First NAS" if self.me == A else "Second NAS")
        monkeypatch.setattr(ha, "audit", lambda *a: None)
        monkeypatch.setattr(ha, "_seen", {})
        monkeypatch.setattr(hs, "_offers", {})
        monkeypatch.setattr(hs, "_state", {"fetching": False, "error": "", "ran": ""})
        monkeypatch.setattr(hs, "PIECE", 1000)
        self.archive = b"ZETTBAK2" + bytes(range(256)) * 10  # 2568 bytes: three pieces
        monkeypatch.setattr(hs, "make_archive", lambda passphrase: self.archive)
        self.on(A)

    def on(self, box):
        self.me = box
        self.patch.setattr(ha, "STATE_FILE", str(self.dirs[box] / "ha.json"))
        self.patch.setattr(hs, "DIR", str(self.dirs[box] / "ha"))

    def send(self, url, body):
        back, target = self.me, next(box for box in self.dirs if url.startswith(box))
        self.on(target)
        try:
            if url.endswith(ha.PAIR_PATH):
                said = ha.accept_pairing(body["box_id"], body["name"], body["address"], body["public"], body["proof"])
            else:
                said = ha.handle_call(copy.deepcopy(body))
        finally:
            self.on(back)
        return said

    def pair(self):
        self.on(A)
        code = ha.new_code("ana")["code"]
        self.on(B)
        ha.pair_with(A, code, B, "ana", send=self.send)


@pytest.fixture
def net(tmp_path, monkeypatch):
    made = Net(tmp_path, monkeypatch)
    made.pair()
    return made


def test_the_second_nas_fetches_the_copy_in_pieces_and_keeps_it_sealed(net):
    assert hs.info() is None
    got = hs.fetch(send=net.send)
    assert (got["size"], got["name"]) == (len(net.archive), "First NAS") and got["fetched"] >= got["made"]
    with open(os.path.join(hs.DIR, hs.COPY), "rb") as f:
        assert f.read() == net.archive  # whole, though it came in three pieces
    assert oct(os.stat(os.path.join(hs.DIR, hs.COPY)).st_mode & 0o777) == "0o600"
    with open(os.path.join(hs.DIR, hs.INFO)) as f:
        kept = json.load(f)
    opens = hs.passphrase()
    assert len(opens) >= 40 and opens not in json.dumps(kept)  # what opens it is sealed where it is kept
    assert "pass" not in hs.info() and "pass" not in hs.view()["copy"]  # and never goes to the screen
    net.on(A)
    assert hs.served() is not None and hs.info() is None
    assert [n for n in os.listdir(hs.DIR) if n.startswith("offer-")] == []  # the first NAS kept no copy lying around


def test_only_the_first_hands_it_over_and_only_the_second_asks(net):
    net.on(A)
    with pytest.raises(ha.LinkError) as e:
        hs.fetch(send=net.send)
    assert e.value.key == "not_second"
    with pytest.raises(ha.LinkError) as e:
        ha.call("settings_begin", send=net.send)  # the first asks the second, which is not a first NAS
    assert e.value.key == "refused"
    net.on(B)
    with pytest.raises(ha.LinkError) as e:
        ha.call("settings_piece", {"id": "nope", "n": 0}, send=net.send)
    assert e.value.key == "refused"


def test_a_copy_that_does_not_arrive_whole_is_not_kept_and_the_old_one_stays(net, monkeypatch):
    hs.fetch(send=net.send)
    first_copy = net.archive
    net.archive = b"ZETTBAK2" + b"new" * 900
    real = ha.call

    def short_piece(op, args=None, send=ha._post):
        said = real(op, args, send=send)
        if op == "settings_piece" and args["n"] == 1:
            said = {"data": said["data"][:-8]}  # a piece that lost its end
        return said

    monkeypatch.setattr(ha, "call", short_piece)
    with pytest.raises(ha.LinkError) as e:
        hs.fetch(send=net.send)
    assert e.value.key == "bad_copy"
    with open(os.path.join(hs.DIR, hs.COPY), "rb") as f:
        assert f.read() == first_copy
    assert not os.path.exists(os.path.join(hs.DIR, hs.COPY + ".new"))


def test_unpairing_forgets_the_copy(net):
    hs.fetch(send=net.send)
    ha.unpair("ana", send=net.send)
    assert hs.info() is None and not os.path.exists(os.path.join(hs.DIR, hs.COPY))
    assert not os.path.exists(os.path.join(hs.DIR, hs.INFO))
    net.on(A)
    assert hs.served() is None  # the first NAS forgot too


def test_the_second_nas_fetches_once_a_night(net, monkeypatch):
    started = []
    monkeypatch.setattr(hs, "fetch_soon", lambda: started.append(1) or True)
    at = time.mktime((2026, 11, 20, 2, 30, 10, 0, 0, -1))
    assert hs.run_due(at - 60) is False and hs.run_due(at) is True and hs.run_due(at + 20) is False
    assert hs.run_due(at + 86400) is True and started == [1, 1]
    net.on(A)
    hs._state["ran"] = ""
    assert hs.run_due(at) is False  # the first NAS fetches nothing


def test_a_fetch_in_the_background_notes_what_went_wrong(net, monkeypatch):
    def fails(send=None):
        raise ha.LinkError("unreachable", "The other NAS did not answer.")

    monkeypatch.setattr(hs, "fetch", fails)
    assert hs.fetch_soon() is True
    for _ in range(100):
        if not hs._state["fetching"]:
            break
        time.sleep(0.01)
    assert hs.view()["fetch_error"] == "unreachable" and hs.view()["fetching"] is False


def test_the_copy_is_the_encrypted_settings_backup_with_the_key_it_needs():
    from backend.services import backup_engine

    data = hs.make_archive("a passphrase made for one copy")
    assert data.startswith(backup_engine.ENCRYPTED_MAGIC)
    plain = backup_engine.decrypt_backup(data, "a passphrase made for one copy")
    with zipfile.ZipFile(io.BytesIO(plain)) as z:
        manifest = json.loads(z.read(backup_engine.MANIFEST_NAME))
    assert manifest["encrypted"] is True and manifest["keys_included"] is True


def test_over_the_api_only_the_second_nas_fetches(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(ha, "STATE_FILE", str(tmp_path / "ha.json"))
    monkeypatch.setattr(hs, "DIR", str(tmp_path / "ha"))
    status = client.get("/api/ha", headers=auth_headers).json()
    assert status["copy"] is None and status["fetching"] is False and status["fetch_at"] == "02:30"
    res = client.post("/api/ha/fetch", headers=auth_headers)
    assert res.status_code == 409 and res.json()["error"] == "ha_not_second"
    assert res.json()["text"]["msg_key"] == "srv.ha_not_second"
    monkeypatch.setattr(ha, "role", lambda: "second")
    started = []
    monkeypatch.setattr(hs, "fetch_soon", lambda: started.append(1) or True)
    assert client.post("/api/ha/fetch", headers=auth_headers).status_code == 200 and started == [1]
