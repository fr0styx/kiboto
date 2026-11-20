"""Windows lists the NAS under "Network": a small WS-Discovery answerer (WSD, the Devices Profile
for Web Services), the way Windows 10 and 11 find computers since the old NetBIOS browsing went.

It runs beside the name responder (mdns_responder.py), in the same container on the host's
network, and only where Kiboto serves the files over SMB itself: a host with its own answerer
(Unraid) keeps that one. Standard library only.

What it does, and no more:
- says Hello on the home network when it starts and Bye when it stops (UDP 239.255.255.250:3702);
- answers a Probe for devices, and a Resolve for its own address, to whoever asked;
- answers the one question Windows then asks over HTTP on port 5357 ("who are you?") with the
  computer's name and workgroup.
Windows opens \\\\NAME from that; the name itself is answered by the name responder.

Messages come from the home network and are not trusted: nothing larger than a small packet is
read, a document type or entity declaration is refused before parsing, and HTTP is answered only
to private addresses.
"""

from __future__ import annotations

import http.server
import ipaddress
import socket
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from typing import Any
from xml.sax.saxutils import escape

GROUP, PORT, HTTP_PORT = "239.255.255.250", 3702, 5357
MAX_PACKET = 8192
MAX_BODY = 16 * 1024
NS = {
    "soap": "http://www.w3.org/2003/05/soap-envelope",
    "wsa": "http://schemas.xmlsoap.org/ws/2004/08/addressing",
    "wsd": "http://schemas.xmlsoap.org/ws/2005/04/discovery",
    "wsdp": "http://schemas.xmlsoap.org/ws/2006/02/devprof",
    "pub": "http://schemas.microsoft.com/windows/pub/2005/07",
    "wsx": "http://schemas.xmlsoap.org/ws/2004/09/mex",
    "wsf": "http://schemas.xmlsoap.org/ws/2004/09/transfer",
    "pnpx": "http://schemas.microsoft.com/windows/pnpx/2005/10",
}
DISCOVERY = NS["wsd"]
TO_ALL = "urn:schemas-xmlsoap-org:ws:2005:04:discovery"
TO_ASKER = "http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous"
ACTION_GET = NS["wsf"] + "/Get"
ACTION_GET_RESPONSE = NS["wsf"] + "/GetResponse"
TYPES = "wsdp:Device pub:Computer"
REMEMBERED = 64  # message ids already answered: a question is sent several times


def device_id(seed: str) -> str:
    """The device's address on the network: the same for the same box and name, every start."""
    return "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_DNS, seed or "kiboto"))


def _envelope(action: str, to: str, body: str, relates_to: str = "", sequence: tuple[int, int] | None = None) -> bytes:
    spaces = " ".join(f'xmlns:{prefix}="{uri}"' for prefix, uri in NS.items())
    head = f"<wsa:To>{escape(to)}</wsa:To><wsa:Action>{escape(action)}</wsa:Action>"
    head += f"<wsa:MessageID>urn:uuid:{uuid.uuid4()}</wsa:MessageID>"
    if relates_to:
        head += f"<wsa:RelatesTo>{escape(relates_to)}</wsa:RelatesTo>"
    if sequence:
        head += f'<wsd:AppSequence InstanceId="{sequence[0]}" MessageNumber="{sequence[1]}"/>'
    return (
        f'<?xml version="1.0" encoding="utf-8"?><soap:Envelope {spaces}>'
        f"<soap:Header>{head}</soap:Header><soap:Body>{body}</soap:Body></soap:Envelope>"
    ).encode()


def parse(data: bytes) -> ET.Element | None:
    """A message as a tree, or None for anything that is not a small plain XML document."""
    if not data or len(data) > MAX_BODY or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


def _text(root: ET.Element, path: str) -> str:
    found = root.find(path, NS)
    return (found.text or "").strip() if found is not None else ""


def _asks_for_devices(types: str) -> bool:
    """Whether a Probe's Types include a device. The prefix is the asker's own choice, so only
    the word after it counts (Windows asks for "wsdp:Device"; a search for printers names another
    type and is not answered). A Probe that names no type asks for everything."""
    return not types or any(word.rpartition(":")[2] == "Device" for word in types.split())


class Device:
    """What this box says of itself, and its answers. No sockets here: easy to test."""

    def __init__(self, name: str, ip: str, workgroup: str = "WORKGROUP", seed: str = "", web_port: int = 0):
        self.name = name
        self.ip = ip
        self.web_port = web_port  # where the NAS's own page is: Windows offers "View device webpage"
        self.workgroup = workgroup or "WORKGROUP"
        self.address = device_id(seed or name)
        self.instance = int(time.time())
        self.sent = 0
        self.answered: list[str] = []

    @property
    def xaddrs(self) -> str:
        return f"http://{self.ip}:{HTTP_PORT}/{self.address.removeprefix('urn:uuid:')}"

    def _sequence(self) -> tuple[int, int]:
        self.sent += 1
        return self.instance, self.sent

    def _endpoint(self) -> str:
        return f"<wsa:EndpointReference><wsa:Address>{self.address}</wsa:Address></wsa:EndpointReference>"

    def hello(self) -> bytes:
        body = (
            f"<wsd:Hello>{self._endpoint()}<wsd:Types>{TYPES}</wsd:Types>"
            f"<wsd:XAddrs>{self.xaddrs}</wsd:XAddrs><wsd:MetadataVersion>1</wsd:MetadataVersion></wsd:Hello>"
        )
        return _envelope(DISCOVERY + "/Hello", TO_ALL, body, sequence=self._sequence())

    def bye(self) -> bytes:
        return _envelope(
            DISCOVERY + "/Bye", TO_ALL, f"<wsd:Bye>{self._endpoint()}</wsd:Bye>", sequence=self._sequence()
        )

    def _seen(self, message_id: str) -> bool:
        if not message_id or message_id in self.answered:
            return True
        self.answered = [*self.answered[-REMEMBERED + 1 :], message_id]
        return False

    def answer(self, data: bytes) -> bytes | None:
        """The answer to one message from the network, or None when there is nothing to say."""
        root = parse(data)
        if root is None:
            return None
        action, message_id = _text(root, "./soap:Header/wsa:Action"), _text(root, "./soap:Header/wsa:MessageID")
        if action == DISCOVERY + "/Probe":
            probe = root.find("./soap:Body/wsd:Probe", NS)
            if probe is None or not _asks_for_devices(_text(probe, "./wsd:Types")) or self._seen(message_id):
                return None
            # no address in the match: Windows then sends a Resolve for it
            body = (
                f"<wsd:ProbeMatches><wsd:ProbeMatch>{self._endpoint()}<wsd:Types>{TYPES}</wsd:Types>"
                "<wsd:MetadataVersion>1</wsd:MetadataVersion></wsd:ProbeMatch></wsd:ProbeMatches>"
            )
            return _envelope(DISCOVERY + "/ProbeMatches", TO_ASKER, body, message_id, self._sequence())
        if action == DISCOVERY + "/Resolve":
            wanted = _text(root, "./soap:Body/wsd:Resolve/wsa:EndpointReference/wsa:Address")
            if wanted != self.address or self._seen(message_id):
                return None
            body = (
                f"<wsd:ResolveMatches><wsd:ResolveMatch>{self._endpoint()}<wsd:Types>{TYPES}</wsd:Types>"
                f"<wsd:XAddrs>{self.xaddrs}</wsd:XAddrs><wsd:MetadataVersion>1</wsd:MetadataVersion>"
                "</wsd:ResolveMatch></wsd:ResolveMatches>"
            )
            return _envelope(DISCOVERY + "/ResolveMatches", TO_ASKER, body, message_id, self._sequence())
        return None

    def describe(self, data: bytes) -> bytes | None:
        """The answer to "who are you?" over HTTP (a WS-Transfer Get), or None for anything else."""
        root = parse(data)
        if root is None or _text(root, "./soap:Header/wsa:Action") != ACTION_GET:
            return None
        if _text(root, "./soap:Header/wsa:To") not in ("", self.address):
            return None
        name, group = escape(self.name), escape(self.workgroup)
        page = f"http://{self.ip}" + ("" if self.web_port in (0, 80) else f":{self.web_port}")
        page = f"<wsdp:PresentationUrl>{page}</wsdp:PresentationUrl>" if self.web_port else ""
        dialect = NS["wsdp"]
        body = (
            "<wsx:Metadata>"
            f'<wsx:MetadataSection Dialect="{dialect}/ThisDevice"><wsdp:ThisDevice>'
            f"<wsdp:FriendlyName>{name}</wsdp:FriendlyName><wsdp:FirmwareVersion>1.0</wsdp:FirmwareVersion>"
            "<wsdp:SerialNumber>1</wsdp:SerialNumber></wsdp:ThisDevice></wsx:MetadataSection>"
            f'<wsx:MetadataSection Dialect="{dialect}/ThisModel"><wsdp:ThisModel>'
            "<wsdp:Manufacturer>Kiboto</wsdp:Manufacturer><wsdp:ModelName>Kiboto NAS</wsdp:ModelName>"
            f"<wsdp:ModelNumber>1</wsdp:ModelNumber>{page}"
            "<pnpx:DeviceCategory>Computers</pnpx:DeviceCategory></wsdp:ThisModel></wsx:MetadataSection>"
            f'<wsx:MetadataSection Dialect="{dialect}/Relationship">'
            f'<wsdp:Relationship Type="{dialect}/host"><wsdp:Host>{self._endpoint()}'
            f"<wsdp:Types>pub:Computer</wsdp:Types><wsdp:ServiceId>{self.address}</wsdp:ServiceId>"
            f"<pub:Computer>{name}/Workgroup:{group}</pub:Computer></wsdp:Host></wsdp:Relationship>"
            "</wsx:MetadataSection></wsx:Metadata>"
        )
        return _envelope(ACTION_GET_RESPONSE, TO_ASKER, body, _text(root, "./soap:Header/wsa:MessageID"))


def _from_home(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _handler(device: Device) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "Kiboto-WSD"
        sys_version = ""

        def log_message(self, *args: Any) -> None:
            return  # nothing is written for a question from the home network

        def _refuse(self, code: int) -> None:
            self.send_response(code)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not _from_home(self.client_address[0]):
                return self._refuse(403)
            if self.path != "/" + device.address.removeprefix("urn:uuid:"):
                return self._refuse(404)
            if not 0 < length <= MAX_BODY:
                return self._refuse(400)
            reply = device.describe(self.rfile.read(length))
            if reply is None:
                return self._refuse(400)
            self.send_response(200)
            self.send_header("Content-Type", "application/soap+xml")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

    return Handler


class Answerer:
    """The device on the network: its UDP socket and its small HTTP server, each on a thread."""

    def __init__(self, device: Device, http_port: int = HTTP_PORT):
        self.device = device
        self.stopping = threading.Event()
        # like the name responder: it listens on the group's address only, not on every interface,
        # and sends from the NAS's own address, both on port 3702
        rx = self._udp((GROUP, PORT))
        tx: socket.socket | None = None
        try:
            member = socket.inet_aton(GROUP) + socket.inet_aton(device.ip)
            rx.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, member)
            rx.settimeout(1.0)
            tx = self._udp((device.ip, PORT))
            tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(device.ip))
            tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            server = http.server.ThreadingHTTPServer((device.ip, http_port), _handler(device))
        except OSError:
            rx.close()
            if tx is not None:
                tx.close()
            raise
        server.daemon_threads = True
        self.rx, self.tx, self.http = rx, tx, server

    @staticmethod
    def _udp(address: tuple[str, int]) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(address)
        except OSError:
            s.close()
            raise
        return s

    def close(self) -> None:
        self.rx.close()
        self.tx.close()
        self.http.server_close()

    def _say(self, message: bytes, times: int = 2) -> None:
        for _ in range(times):
            try:
                self.tx.sendto(message, (GROUP, PORT))
            except OSError:
                return
            time.sleep(0.1)

    def _listen(self) -> None:
        while not self.stopping.is_set():
            try:
                data, asker = self.rx.recvfrom(MAX_PACKET)
            except TimeoutError:
                continue
            except OSError:
                return
            reply = self.device.answer(data) if _from_home(asker[0]) else None
            if reply:
                try:
                    self.tx.sendto(reply, asker)
                except OSError:
                    continue

    def start(self) -> Answerer:
        threading.Thread(target=self.http.serve_forever, name="wsd-http", daemon=True).start()
        threading.Thread(target=self._listen, name="wsd-udp", daemon=True).start()
        self._say(self.device.hello())
        return self

    def stop(self) -> None:
        self._say(self.device.bye())
        self.stopping.set()
        self.http.shutdown()
        self.close()


def start(name: str, ip: str, workgroup: str = "WORKGROUP", seed: str = "", web_port: int = 0) -> Answerer | None:
    """Starts answering, or says why not and returns None: another answerer already has the port
    (the host's own), which is left alone."""
    try:
        made = Answerer(Device(name, ip, workgroup, seed, web_port)).start()
    except OSError as e:
        print(
            f"[wsd] not started ({e}); if the host has its own answerer, Windows finds the NAS through that", flush=True
        )
        return None
    print(f"[wsd] {name} is listed for Windows PCs on {ip} (workgroup {workgroup})", flush=True)
    return made
