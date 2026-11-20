"""High availability, the link between two boxes (the owner's decisions of 19 Nov 2026: it must
work on the home network without Tailscale, so it brings its own encryption). Two boxes are played
here by one process that switches whose state file is in use; what one "sends" is handed to the
other's own handler, as the network would."""

import base64
import copy
import time

import pytest

from backend.services import ha_link as ha

A, B = "http://192.168.1.10:8082", "http://192.168.1.20:8082"


class Net:
    """Two boxes, "first" at A and "second" at B, and the wire between them."""

    def __init__(self, tmp_path, monkeypatch):
        self.files = {A: str(tmp_path / "first.json"), B: str(tmp_path / "second.json")}
        self.patch, self.me, self.wire, self.tamper, self.down = monkeypatch, A, [], None, False
        monkeypatch.setattr(ha, "my_name", lambda: "First NAS" if self.me == A else "Second NAS")
        monkeypatch.setattr(ha, "audit", lambda *a: None)
        monkeypatch.setattr(ha, "_seen", {})
        self.on(A)

    def on(self, box):
        self.me = box
        self.patch.setattr(ha, "STATE_FILE", self.files[box])

    def send(self, url, body):
        """What box `self.me` sends to the other one; `tamper` is someone in between."""
        if self.down:
            raise ha.LinkError("unreachable", "The other NAS did not answer.")
        back, target = self.me, next(box for box in self.files if url.startswith(box))
        body = copy.deepcopy(body)
        if self.tamper:
            body = self.tamper("out", body) or body
        self.wire.append(copy.deepcopy(body))
        self.on(target)
        try:
            if url.endswith(ha.PAIR_PATH):
                said = ha.accept_pairing(body["box_id"], body["name"], body["address"], body["public"], body["proof"])
            else:
                said = ha.handle_call(body)
        finally:
            self.on(back)
        said = copy.deepcopy(said)
        if self.tamper:
            said = self.tamper("back", said) or said
        return said

    def pair(self):
        self.on(A)
        code = ha.new_code("ana")["code"]
        self.on(B)
        return ha.pair_with(A, code, B, "ana", send=self.send)


@pytest.fixture
def net(tmp_path, monkeypatch):
    return Net(tmp_path, monkeypatch)


def test_the_pairing_key_is_long_and_has_no_signs_that_look_alike():
    code = ha.new_code_text()
    assert len(code) == 19 and code.count("-") == 3 and not set(code) & set("01IO")
    assert len(set(ha.CODE_ALPHABET)) == 32 and ha.CODE_SIGNS * 5 == 80  # 80 random bits
    assert ha._norm("abcd-efgh jkmn\tpqrs") == "ABCDEFGHJKMNPQRS"


def test_two_boxes_pair_and_share_a_key_that_never_travelled(net):
    status = net.pair()
    assert status["role"] == "second" and status["peer"]["name"] == "First NAS" and status["peer"]["address"] == A
    key_second = ha._key_of(ha.peer())
    net.on(A)
    assert ha.role() == "first" and ha.peer()["name"] == "Second NAS" and ha.peer()["address"] == B
    assert ha._key_of(ha.peer()) == key_second and len(key_second) == 32
    assert ha.status()["code_waiting"] is False  # the pairing key was used: it is gone
    sent = str(net.wire)
    assert base64.b64encode(key_second).decode() not in sent  # neither the key ...
    assert "key" not in ha.status()["peer"] and "key" not in str(ha.status())  # ... nor does the screen get it
    with open(net.files[A]) as f:
        assert base64.b64encode(key_second).decode() not in f.read()  # and it is sealed where it is kept


def test_without_the_right_pairing_key_nothing_pairs_and_five_tries_end_it(net):
    net.on(A)
    ha.new_code()
    net.on(B)
    for n in range(ha.CODE_TRIES):
        with pytest.raises(ha.LinkError) as e:
            ha.pair_with(A, "AAAA-BBBB-CCCC-DDDD", B, send=net.send)
        assert e.value.key == "bad_pairing", n
    assert ha.peer() is None
    net.on(A)
    assert ha.peer() is None and ha.status()["code_waiting"] is False  # the key is gone after five wrong tries
    net.on(B)
    with pytest.raises(ha.LinkError) as e:
        ha.pair_with(A, "AAAA-BBBB-CCCC-DDDD", B, send=net.send)
    assert e.value.key == "no_code"
    with pytest.raises(ha.LinkError) as e:
        ha.pair_with(A, "too short", B, send=net.send)
    assert e.value.key == "bad_pairing"


def test_a_pairing_key_is_good_for_ten_minutes_and_one_pairing(net, monkeypatch):
    net.on(A)
    code = ha.new_code()["code"]
    real = time.time
    monkeypatch.setattr(ha.time, "time", lambda: real() + ha.CODE_SECONDS + 1)
    net.on(B)
    with pytest.raises(ha.LinkError) as e:
        ha.pair_with(A, code, B, send=net.send)
    assert e.value.key == "no_code"
    monkeypatch.setattr(ha.time, "time", real)
    net.pair()
    net.on(A)
    with pytest.raises(ha.LinkError) as e:
        ha.new_code()
    assert e.value.key == "paired"
    net.on(B)
    with pytest.raises(ha.LinkError) as e:
        ha.pair_with(A, code, B, send=net.send)
    assert e.value.key == "paired"


def test_someone_in_between_cannot_swap_a_key_in_either_direction(net):
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    theirs = ha._public(X25519PrivateKey.generate())

    def swap_on_the_way_out(way, body):
        if way == "out" and "public" in body:
            body["public"] = theirs
        return body

    def swap_on_the_way_back(way, body):
        if way == "back" and "public" in body:
            body["public"] = theirs
        return body

    net.on(A)
    code = ha.new_code()["code"]
    net.on(B)
    net.tamper = swap_on_the_way_out
    with pytest.raises(ha.LinkError) as e:
        ha.pair_with(A, code, B, send=net.send)
    assert e.value.key == "bad_pairing" and ha.peer() is None
    net.on(A)
    assert ha.peer() is None
    net.on(B)
    net.tamper = swap_on_the_way_back
    with pytest.raises(ha.LinkError) as e:
        ha.pair_with(A, code, B, send=net.send)
    assert e.value.key == "bad_pairing" and ha.peer() is None  # the second NAS does not trust the swapped key


def test_the_boxes_talk_both_ways_and_only_they_can_read_it(net):
    net.pair()
    said = ha.call("hello", send=net.send)
    assert said["name"] == "First NAS" and said["role"] == "first"
    asked = net.wire[-1]
    assert set(asked) == {"from", "n", "c"} and "hello" not in str(asked)  # sealed: the wire shows no words
    net.on(A)
    assert ha.call("hello", send=net.send)["name"] == "Second NAS"
    assert ha.status()["peer"]["reachable"] is True
    with pytest.raises(ha.LinkError) as e:
        ha.call("no-such-request", send=net.send)
    assert e.value.key == "refused"


def test_a_changed_repeated_or_strange_message_is_refused(net, monkeypatch):
    net.pair()
    ha.call("hello", send=net.send)
    asked = net.wire[-1]
    net.on(A)
    with pytest.raises(ha.LinkError) as e:
        ha.handle_call(asked)  # the same message a second time
    assert e.value.key == "bad_message"
    changed = dict(asked, c=asked["c"][:-4] + ("AAAA" if not asked["c"].endswith("AAAA") else "BBBB"))
    with pytest.raises(ha.LinkError) as e:
        ha.handle_call(changed)
    assert e.value.key == "bad_message"
    with pytest.raises(ha.LinkError) as e:
        ha.handle_call(dict(asked, **{"from": "0" * 16}))  # not the paired box
    assert e.value.key == "not_paired"
    # a message made a while ago (someone kept it and sends it later)
    net.on(B)
    key, mine, other = ha._key_of(ha.peer()), ha.box_id(), ha.peer()["id"]
    real = time.time
    monkeypatch.setattr(ha.time, "time", lambda: real() - ha.CLOCK_SLACK_SECS - 5)
    old = ha.seal(key, mine, other, {"op": "hello", "args": {}})
    monkeypatch.setattr(ha.time, "time", real)
    net.on(A)
    with pytest.raises(ha.LinkError) as e:
        ha.handle_call(old)
    assert e.value.key == "clock"


def test_an_answer_belongs_to_its_own_question(net):
    net.pair()
    kept = []

    def keep_then_replay(way, body):
        if way == "back":
            kept.append(body)
            return kept[0]  # every later question gets the first answer again
        return body

    net.tamper = keep_then_replay
    assert ha.call("hello", send=net.send)["name"] == "First NAS"
    with pytest.raises(ha.LinkError) as e:
        ha.call("hello", send=net.send)
    assert e.value.key == "bad_message" and ha.status()["peer"]["reachable"] is False


@pytest.mark.parametrize(
    "address",
    [
        "http://192.168.1.20:8082",
        "https://10.0.0.5",
        "http://172.16.4.4:8082/",
        "http://100.90.1.2:8082",
        "https://nas.tail1234.ts.net",
        "http://[fd7a:115c:a1e0::1]:8082",
        "http://[fd00::20]:8082",
    ],
)
def test_an_address_on_the_home_network_or_tailscale_is_taken(address):
    assert ha.clean_address(f"  {address} ") == address.rstrip("/")


@pytest.mark.parametrize(
    "address,key",
    [
        ("http://8.8.8.8:8082", "not_home"),
        ("http://127.0.0.1:8082", "not_home"),
        ("http://0.0.0.0:8082", "not_home"),
        ("http://nas.example.com:8082", "bad_address"),  # a name: Kiboto does not look names up for this
        ("http://kiboto.local:8082", "bad_address"),
        ("ftp://192.168.1.20", "bad_address"),
        ("http://192.168.1.20:8082/api", "bad_address"),
        ("http://192.168.1.20:8082?x=1", "bad_address"),
        ("http://me:secret@192.168.1.20:8082", "bad_address"),
        ("192.168.1.20", "bad_address"),
        ("", "bad_address"),
    ],
)
def test_any_other_address_is_refused(address, key):
    with pytest.raises(ha.LinkError) as e:
        ha.clean_address(address)
    assert e.value.key == key


def test_unpairing_tells_the_other_box_and_works_without_it(net):
    net.pair()
    assert ha.unpair("ana", send=net.send)["role"] == "" and ha.peer() is None
    net.on(A)
    assert ha.peer() is None and ha.role() == ""  # the first NAS was told and forgot too
    net.pair()
    net.down = True
    assert ha.unpair("ana", send=net.send)["peer"] is None  # not reachable: this side is unpaired all the same
    net.on(A)
    assert ha.peer() is not None  # that side keeps its part until it is unpaired there
    with pytest.raises(ha.LinkError) as e:
        net.on(B)
        ha.call("hello", send=net.send)
    assert e.value.key == "not_paired"


def test_checking_says_whether_the_other_box_is_there(net):
    net.pair()
    status = ha.check(send=net.send)
    assert status["peer"]["reachable"] is True and status["peer"]["said"]["name"] == "First NAS"
    net.down = True
    status = ha.check(send=net.send)
    assert status["peer"]["reachable"] is False and status["peer"]["error"] == "unreachable"


def test_the_other_boxs_own_reason_is_passed_on(monkeypatch):
    import io
    import urllib.error

    def refusing(body, code=403):
        class Opener:
            def open(self, req, timeout=0):
                raise urllib.error.HTTPError(req.full_url, code, "Forbidden", None, io.BytesIO(body))

        monkeypatch.setattr(ha.urllib.request, "build_opener", lambda *a: Opener())

    for body, key in (
        (b'{"error": "ha_bad_pairing", "message": "The pairing key is not right."}', "bad_pairing"),
        (b'{"error": "ha_no_code"}', "no_code"),
        (b'{"error": "ha_something_new"}', "refused"),
        (b'{"error": "rate_limited"}', "refused"),
        (b"<html>not ours</html>", "refused"),
    ):
        refusing(body)
        with pytest.raises(ha.LinkError) as e:
            ha._post(A + ha.PAIR_PATH, {})
        assert e.value.key == key, body


# --- over the API ---------------------------------------------------------------------------------
def test_only_someone_who_may_change_the_system_reaches_the_owners_routes(client, monkeypatch):
    monkeypatch.setattr(
        "backend.auth.get_current_session",
        lambda tok: {
            "user_id": "u_sam",
            "username": "sam",
            "role_id": "viewer",
            "scopes": ["system:view", "storage:admin"],
        },
    )
    h = {"Authorization": "Bearer x"}
    for method, path, body in [
        ("get", "/api/ha", None),
        ("post", "/api/ha/code", None),
        ("post", "/api/ha/pair", {"address": A, "code": "AAAA-BBBB-CCCC-DDDD", "my_address": B}),
        ("delete", "/api/ha", None),
        ("post", "/api/ha/check", None),
    ]:
        assert client.request(method, path, json=body, headers=h).status_code == 403, (method, path)


def test_the_other_boxs_routes_need_no_sign_in_and_give_nothing_to_a_stranger(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ha, "STATE_FILE", str(tmp_path / "ha.json"))
    pair = {"box_id": "ab" * 8, "name": "x", "address": B, "public": "A" * 43 + "=", "proof": "0" * 64}
    res = client.post("/api/ha/peer/pair", json=pair)
    assert res.status_code == 403 and res.json()["error"] == "ha_no_code"  # no pairing key is waiting
    res = client.post("/api/ha/peer/call", json={"from": "ab" * 8, "n": "A" * 16, "c": "A" * 40})
    assert res.status_code == 403 and res.json()["error"] == "ha_not_paired"
    assert client.post("/api/ha/peer/call", json={"from": "not hex", "n": "A" * 16, "c": "A" * 40}).status_code == 422


def test_the_owner_makes_a_key_pairs_checks_and_unpairs(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(ha, "STATE_FILE", str(tmp_path / "ha.json"))
    monkeypatch.setattr(ha, "audit", lambda *a: None)
    assert client.get("/api/ha", headers=auth_headers).json()["role"] == ""
    made = client.post("/api/ha/code", headers=auth_headers).json()
    assert len(made["code"]) == 19 and made["valid_seconds"] == 600
    assert client.get("/api/ha", headers=auth_headers).json()["code_waiting"] is True
    asked, fetched = [], []
    monkeypatch.setattr(ha, "pair_with", lambda address, code, mine, actor="": asked.append((address, code, mine)))
    monkeypatch.setattr("backend.services.ha_state.fetch_soon", lambda: fetched.append(1) or True)
    body = {"address": A + "/", "code": made["code"], "my_address": B}
    paired = client.post("/api/ha/pair", json=body, headers=auth_headers)
    assert paired.status_code == 200 and {"role", "peer", "copy", "fetching"} <= set(paired.json())
    assert asked == [(A, made["code"], B)] and fetched == [
        1
    ]  # the first copy of people and settings is fetched at once
    bad = client.post("/api/ha/pair", json=dict(body, address="http://8.8.8.8:8082"), headers=auth_headers)
    assert (
        bad.status_code == 400
        and bad.json()["error"] == "ha_not_home"
        and bad.json()["text"]["msg_key"] == "srv.ha_not_home"
    )
    assert client.post("/api/ha/check", headers=auth_headers).status_code == 200
    assert client.delete("/api/ha", headers=auth_headers).json()["role"] == ""


@pytest.mark.real_confirmations
def test_pairing_and_unpairing_ask_first(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(ha, "STATE_FILE", str(tmp_path / "ha.json"))
    body = {"address": A, "code": "AAAA-BBBB-CCCC-DDDD", "my_address": B}
    assert client.post("/api/ha/pair", json=body, headers=auth_headers).status_code == 428
    assert client.delete("/api/ha", headers=auth_headers).status_code == 428
    made = client.post("/api/confirmations", json={"action": "ha.pair", "target": A}, headers=auth_headers)
    assert made.status_code == 200 and A in made.json()["summary"]


# --- how many messages the other box may send ---------------------------------------------------------
def _paired_over_the_api(client, tmp_path, monkeypatch):
    """This process is the first NAS behind the real route; the second one is played by hand.
    Returns (key, the first's id, the second's id)."""
    net = Net(tmp_path, monkeypatch)
    net.pair()
    net.on(B)
    key, second, first = ha._key_of(ha.peer()), ha.box_id(), ha.peer()["id"]
    net.on(A)
    return key, first, second


def test_readable_messages_are_not_held_back(client, tmp_path, monkeypatch):
    from backend import rate_limit

    rate_limit.reset()
    key, first, second = _paired_over_the_api(client, tmp_path, monkeypatch)
    for _ in range(300):  # a folder of 300 files is 300 messages within seconds
        res = client.post("/api/ha/peer/call", json=ha.seal(key, second, first, {"op": "hello", "args": {}}))
        assert res.status_code == 200, res.text


def test_unreadable_messages_are_limited_per_address(client, tmp_path, monkeypatch):
    from backend import rate_limit
    from backend.api.ha import PEER_UNREADABLE

    rate_limit.reset()
    key, first, second = _paired_over_the_api(client, tmp_path, monkeypatch)
    bad = {"from": second, "n": "A" * 16, "c": "A" * 40}
    for _ in range(PEER_UNREADABLE[0]):
        assert client.post("/api/ha/peer/call", json=bad).status_code == 403
    res = client.post("/api/ha/peer/call", json=bad)
    assert res.status_code == 429 and int(res.headers["Retry-After"]) >= 1
    # the paired box at that address waits too, and is let in again afterwards
    good = ha.seal(key, second, first, {"op": "hello", "args": {}})
    assert client.post("/api/ha/peer/call", json=good).status_code == 429
    rate_limit.reset()
    assert client.post("/api/ha/peer/call", json=good).status_code == 200


def test_waiting_counts_nothing():
    from backend import rate_limit

    rate_limit.reset()
    assert rate_limit.waiting("t:x", 2, 60) == 0
    assert rate_limit.hit("t:x", 2, 60) == 0 and rate_limit.hit("t:x", 2, 60) == 0
    assert rate_limit.waiting("t:x", 2, 60) >= 1 and rate_limit.waiting("t:x", 3, 60) == 0
    assert rate_limit.waiting("t:x", 2, 0) == 0  # the window has passed
    rate_limit.reset()


def test_a_patient_call_asks_again_when_told_later(tmp_path, monkeypatch):
    net = Net(tmp_path, monkeypatch)
    net.pair()
    net.on(B)
    slept, turned_away = [], [3]

    def busy(url, body):
        if turned_away[0]:
            turned_away[0] -= 1
            raise ha.LinkError("refused", "The other NAS refused (429).", wait=7.0)
        return net.send(url, body)

    monkeypatch.setattr(ha.time, "sleep", slept.append)
    assert ha.call("hello", send=busy, patient=True)["name"] == "First NAS"
    assert slept == [7.0, 7.0, 7.0] and ha.status()["peer"]["reachable"] is True
    # a person does not wait: the refusal comes at once
    turned_away[0] = 1
    with pytest.raises(ha.LinkError) as e:
        ha.call("hello", send=busy)
    assert e.value.key == "refused" and slept == [7.0, 7.0, 7.0]
    # and patience ends
    turned_away[0] = ha.BUSY_TRIES + 1
    with pytest.raises(ha.LinkError):
        ha.call("hello", send=busy, patient=True)
    assert len(slept) == 3 + ha.BUSY_TRIES and ha.status()["peer"]["reachable"] is False


def test_how_long_to_wait_is_read_from_the_refusal():
    import io
    import urllib.error
    from email.message import Message

    def refusal(code, later=None):
        headers = Message()
        if later is not None:
            headers["Retry-After"] = later
        return urllib.error.HTTPError("http://x", code, "no", headers, io.BytesIO(b"{}"))

    assert ha._later(refusal(403, "30")) == 0.0
    assert ha._later(refusal(429, "30")) == 30.0
    assert ha._later(refusal(429)) == 1.0
    assert ha._later(refusal(429, "9999")) == ha.BUSY_WAIT_MAX
    assert ha._later(refusal(429, "soon")) == ha.BUSY_WAIT_MAX
