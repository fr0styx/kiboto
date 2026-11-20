"""Windows lists the NAS under Network: the WS-Discovery answerer. The messages are the ones a
Windows PC sends when it looks for computers; what comes back is read the way it reads it."""

import http.server
import threading
import urllib.error
import urllib.request

import pytest

from backend.services import wsd_responder as w

SPACES = " ".join(f'xmlns:{p}="{u}"' for p, u in w.NS.items())


def message(action, body, message_id="urn:uuid:1", to=w.TO_ALL):
    return (
        f'<?xml version="1.0" encoding="utf-8"?><soap:Envelope {SPACES}><soap:Header><wsa:To>{to}</wsa:To>'
        f"<wsa:Action>{action}</wsa:Action><wsa:MessageID>{message_id}</wsa:MessageID></soap:Header>"
        f"<soap:Body>{body}</soap:Body></soap:Envelope>"
    ).encode()


def probe(types="wsdp:Device", message_id="urn:uuid:1"):
    inner = f"<wsd:Types>{types}</wsd:Types>" if types is not None else ""
    return message(w.DISCOVERY + "/Probe", f"<wsd:Probe>{inner}</wsd:Probe>", message_id)


def resolve(address, message_id="urn:uuid:2"):
    body = f"<wsd:Resolve><wsa:EndpointReference><wsa:Address>{address}</wsa:Address></wsa:EndpointReference></wsd:Resolve>"
    return message(w.DISCOVERY + "/Resolve", body, message_id)


@pytest.fixture
def device():
    return w.Device("familynas", "192.168.1.10", "HOME", seed="box-1")


def said(data, path):
    return w._text(w.parse(data), path)


def test_the_device_has_one_address_for_one_box():
    assert w.device_id("box-1") == w.device_id("box-1") != w.device_id("box-2")
    assert w.device_id("box-1").startswith("urn:uuid:") and w.device_id("").startswith("urn:uuid:")
    assert w.Device("a", "10.0.0.2").address == w.device_id("a")  # no mark of the box: made from the name
    assert w.Device("a", "10.0.0.2", "").workgroup == "WORKGROUP"


def test_a_search_for_computers_is_answered_once_and_to_the_question(device):
    reply = device.answer(probe())
    assert said(reply, "./soap:Header/wsa:Action") == w.DISCOVERY + "/ProbeMatches"
    assert said(reply, "./soap:Header/wsa:RelatesTo") == "urn:uuid:1"
    assert said(reply, "./soap:Header/wsa:To") == w.TO_ASKER
    assert said(reply, ".//wsd:ProbeMatch/wsa:EndpointReference/wsa:Address") == device.address
    assert said(reply, ".//wsd:ProbeMatch/wsd:Types") == "wsdp:Device pub:Computer"
    assert device.answer(probe()) is None  # the same question again (it is sent several times)
    assert device.answer(probe(message_id="urn:uuid:9")) is not None
    # the prefix is the asker's own; a search that names no type asks for everything
    assert device.answer(probe("d:Device", "urn:uuid:10")) is not None
    assert device.answer(probe(None, "urn:uuid:11")) is not None
    # a search for printers, or one without an id, is not for this box
    assert device.answer(probe("wprt:PrintDeviceType", "urn:uuid:12")) is None
    assert device.answer(probe(message_id="")) is None
    assert device.answer(message(w.DISCOVERY + "/Probe", "", "urn:uuid:13")) is None


def test_its_address_is_told_to_who_asks_for_this_device(device):
    reply = device.answer(resolve(device.address))
    assert said(reply, "./soap:Header/wsa:Action") == w.DISCOVERY + "/ResolveMatches"
    assert said(reply, ".//wsd:XAddrs") == f"http://192.168.1.10:5357/{device.address.removeprefix('urn:uuid:')}"
    assert device.answer(resolve(device.address)) is None  # asked again
    assert device.answer(resolve("urn:uuid:somebody-else", "urn:uuid:3")) is None


def test_hello_and_bye_and_what_is_not_answered(device):
    hello, bye = device.hello(), device.bye()
    assert said(hello, "./soap:Header/wsa:Action") == w.DISCOVERY + "/Hello" and said(hello, ".//wsd:XAddrs")
    assert said(bye, "./soap:Header/wsa:Action") == w.DISCOVERY + "/Bye"
    first = w.parse(hello).find("./soap:Header/wsd:AppSequence", w.NS)
    second = w.parse(bye).find("./soap:Header/wsd:AppSequence", w.NS)
    assert int(second.get("MessageNumber")) == int(first.get("MessageNumber")) + 1  # counted up
    assert device.answer(hello) is None  # another device's hello
    for junk in (
        b"",
        b"not xml",
        b"<a>",
        b"<!DOCTYPE a><a/>",
        b'<!ENTITY x "y"><a/>',
        b"<a>" + b"x" * w.MAX_BODY + b"</a>",
    ):
        assert w.parse(junk) is None and device.answer(junk) is None and device.describe(junk) is None


def test_only_plain_utf8_is_parsed():
    plain = b'<?xml version="1.0" encoding="UTF-8"?><a/>'
    assert w.parse(plain) is not None and w.parse(b"<a/>") is not None
    assert w.parse(b"<?xml version='1.0' encoding='utf-8' ?><a/>") is not None
    for other in (
        b'<?xml version="1.0" encoding="x-foo"?><a/>',  # the parser answers this with a LookupError
        b'<?xml version="1.0" encoding="shift_jis"?><a/>',  # and this with a ValueError
        b'<?xml version="1.0" encoding="utf-7"?><a/>',
        b'<?xml version="1.0" encoding="iso-8859-1"?><a/>',
        "<a/>".encode("utf-16"),  # a document type in UTF-16 would pass the check for one
        '<!DOCTYPE a [<!ENTITY b "c">]><a>&b;</a>'.encode("utf-16-le"),
        b"<a>\x00</a>",
        b"<a>",
        b"",
    ):
        assert w.parse(other) is None, other


def test_a_message_in_another_encoding_does_not_end_the_listener(device):
    for odd in (b'<?xml version="1.0" encoding="x-foo"?><a/>', b'<?xml version="1.0" encoding="shift_jis"?><a/>'):
        assert device.answer(odd) is None and device.describe(odd) is None
    assert device.answer(probe(message_id="urn:uuid:21")) is not None  # the next real question is answered


def test_who_are_you_is_answered_with_the_name_and_the_workgroup(device):
    get = message(w.ACTION_GET, "", "urn:uuid:7", to=device.address)
    reply = device.describe(get)
    assert said(reply, "./soap:Header/wsa:Action") == w.ACTION_GET_RESPONSE
    assert said(reply, "./soap:Header/wsa:RelatesTo") == "urn:uuid:7"
    assert said(reply, ".//wsdp:Host/pub:Computer") == "familynas/Workgroup:HOME"
    assert said(reply, ".//wsdp:Host/wsdp:Types") == "pub:Computer"
    assert said(reply, ".//wsdp:FriendlyName") == "familynas" and said(reply, ".//pnpx:DeviceCategory") == "Computers"
    assert w.parse(reply).find(".//wsdp:PresentationUrl", w.NS) is None  # no page told: none offered
    for port, url in ((8082, "http://192.168.1.10:8082"), (80, "http://192.168.1.10")):
        with_page = w.Device("familynas", "192.168.1.10", "HOME", "box-1", web_port=port)
        assert (
            said(with_page.describe(message(w.ACTION_GET, "", to=with_page.address)), ".//wsdp:PresentationUrl") == url
        )
    assert device.describe(message(w.ACTION_GET, "", to="urn:uuid:somebody-else")) is None
    assert device.describe(probe()) is None  # not that question
    odd = w.Device("a<b&c", "10.0.0.2", "W&G")
    assert said(odd.describe(message(w.ACTION_GET, "", to=odd.address)), ".//pub:Computer") == "a<b&c/Workgroup:W&G"


def test_the_question_over_http(device):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), w._handler(device))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    path = "/" + device.address.removeprefix("urn:uuid:")

    def post(url, data, headers=None):
        req = urllib.request.Request(url, data=data, headers=headers or {"Content-Type": "application/soap+xml"})
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, res.headers.get("Content-Type"), res.read()
        except urllib.error.HTTPError as e:
            return e.code, None, b""

    try:
        code, kind, body = post(base + path, message(w.ACTION_GET, "", to=device.address))
        assert code == 200 and kind == "application/soap+xml"
        assert said(body, ".//pub:Computer") == "familynas/Workgroup:HOME"
        assert post(base + "/somewhere-else", message(w.ACTION_GET, ""))[0] == 404
        assert post(base + path, probe())[0] == 400  # not the question it answers
        assert post(base + path, b"x" * (w.MAX_BODY + 1))[0] == 400
    finally:
        server.shutdown()
        server.server_close()


def test_only_the_home_network_is_answered(device, monkeypatch):
    assert w._from_home("192.168.1.7") and w._from_home("10.1.2.3") and w._from_home("127.0.0.1")
    assert w._from_home("169.254.3.4") and not w._from_home("8.8.8.8") and not w._from_home("not an address")
    handler = w._handler(device)
    refused = []
    fake = handler.__new__(handler)
    fake.client_address = ("8.8.8.8", 4000)
    fake.headers = {"Content-Length": "12"}
    fake.path = "/" + device.address.removeprefix("urn:uuid:")
    fake._refuse = refused.append
    fake.do_POST()
    fake.client_address = ("192.168.1.7", 4000)
    fake.headers = {"Content-Length": "many"}
    fake.do_POST()
    assert refused == [403, 400]
    assert fake.log_message("%s", "x") is None


class Wire:
    """A socket that keeps what is sent and hands out what was queued."""

    def __init__(self, incoming=()):
        self.sent, self.incoming, self.closed = [], list(incoming), False

    def sendto(self, data, addr):
        self.sent.append((data, addr))
        return len(data)

    def recvfrom(self, size):
        if not self.incoming:
            raise OSError("closed")
        item = self.incoming.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


def bare(device, rx, tx):
    made = w.Answerer.__new__(w.Answerer)
    made.device, made.stopping, made.rx, made.tx = device, threading.Event(), rx, tx
    made.http = type(
        "H", (), {"shutdown": lambda self: None, "server_close": lambda self: None, "serve_forever": lambda self: None}
    )()
    return made


def test_on_the_network_it_says_hello_answers_and_says_bye(device, monkeypatch):
    monkeypatch.setattr(w.time, "sleep", lambda s: None)
    asker, stranger = ("192.168.1.7", 51000), ("8.8.8.8", 51000)
    rx = Wire([TimeoutError(), (probe(), asker), (probe(message_id="urn:uuid:5"), stranger), (b"junk", asker)])
    tx = Wire()
    made = bare(device, rx, tx)
    made._listen()  # until the socket is closed
    assert len(tx.sent) == 1 and tx.sent[0][1] == asker  # the stranger and the junk get nothing
    assert said(tx.sent[0][0], "./soap:Header/wsa:Action").endswith("/ProbeMatches")
    monkeypatch.setattr(
        w.threading, "Thread", lambda target=None, name="", daemon=False: type("T", (), {"start": lambda self: None})()
    )
    made.start()
    hellos = [d for d, a in tx.sent if a == (w.GROUP, w.PORT)]
    assert len(hellos) == 2 and said(hellos[0], "./soap:Header/wsa:Action").endswith("/Hello")
    made.stop()
    assert said(tx.sent[-1][0], "./soap:Header/wsa:Action").endswith("/Bye") and rx.closed and tx.closed
    assert made.stopping.is_set()

    class Broken(Wire):
        def sendto(self, data, addr):
            raise OSError("network is down")

    quiet = bare(device, Wire([(probe(message_id="urn:uuid:6"), asker)]), Broken())
    quiet._listen()  # an answer that cannot be sent is dropped
    quiet._say(device.hello())


def test_a_port_that_is_taken_is_left_to_whoever_has_it(monkeypatch, capsys):
    def taken(address):
        raise OSError(98, "Address already in use")

    monkeypatch.setattr(w.Answerer, "_udp", staticmethod(taken))
    assert w.start("familynas", "192.168.1.10") is None
    assert "not started" in capsys.readouterr().out
    closed = []

    class Part:
        def __init__(self, fails):
            self.fails = fails

        def setsockopt(self, *a):
            if self.fails:
                raise OSError("no such interface")

        def settimeout(self, value):
            return None

        def close(self):
            closed.append(1)

    monkeypatch.setattr(w.Answerer, "_udp", staticmethod(lambda address: Part(True)))
    assert w.start("familynas", "192.168.1.10") is None and closed == [1]  # what was opened is closed again
    # both sockets are there, and the port for the question over HTTP is taken (the host's own answerer)
    closed.clear()
    monkeypatch.setattr(w.Answerer, "_udp", staticmethod(lambda address: Part(False)))

    def no_server(address, handler):
        raise OSError(98, "Address already in use")

    monkeypatch.setattr(w.http.server, "ThreadingHTTPServer", no_server)
    assert w.start("familynas", "192.168.1.10") is None and closed == [1, 1]
    started = []
    monkeypatch.setattr(
        w, "Answerer", lambda device: type("A", (), {"start": lambda self: started.append(device.name) or self})()
    )
    assert w.start("familynas", "192.168.1.10", "HOME", "box-1") is not None and started == ["familynas"]
    assert "is listed for Windows PCs" in capsys.readouterr().out


def test_a_real_socket_is_opened_and_closed_again():
    s = w.Answerer._udp(("127.0.0.1", 0))
    port = s.getsockname()[1]
    assert port > 0
    s.close()
