"""How to connect: the home-network address of the shared folders (SET-22, Shares 3)."""


def test_the_address_is_the_nas_on_the_home_network(client, auth_headers, monkeypatch):
    monkeypatch.setattr("backend.hardware.net.topology.read_ip", lambda: "192.168.1.20")
    r = client.get("/api/storage/connect", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"address": "192.168.1.20"}


def test_no_address_is_an_empty_answer_not_an_error(client, auth_headers, monkeypatch):
    def broken():
        raise OSError("no network file")

    monkeypatch.setattr("backend.hardware.net.topology.read_ip", broken)
    assert client.get("/api/storage/connect", headers=auth_headers).json() == {"address": ""}


def test_signed_out_gets_nothing(client):
    assert client.get("/api/storage/connect").status_code == 401
