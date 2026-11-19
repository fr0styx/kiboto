"""Re-audit R2: the speed test between a device and the NAS."""

from backend.api import speedtest


def _login(client):
    res = client.post("/api/auth/login", json={"password": "admin"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_it_needs_a_signed_in_person(client):
    for method, path in (
        ("get", "/api/network/speedtest/ping"),
        ("get", "/api/network/speedtest/download?mb=1"),
        ("post", "/api/network/speedtest/upload"),
    ):
        assert getattr(client, method)(path).status_code in (401, 403)


def test_download_sends_exactly_what_was_asked_and_it_does_not_compress(client):
    import zlib

    res = client.get("/api/network/speedtest/download?mb=1", headers=_login(client))
    assert res.status_code == 200
    assert len(res.content) == 1024 * 1024
    assert res.headers["cache-control"] == "no-store"
    assert len(zlib.compress(res.content)) > 0.99 * len(res.content)


def test_download_is_capped(client):
    h = _login(client)
    assert client.get("/api/network/speedtest/download?mb=0", headers=h).status_code == 422
    assert (
        client.get(f"/api/network/speedtest/download?mb={speedtest.MAX_DOWNLOAD_MB + 1}", headers=h).status_code == 422
    )


def test_the_pieces_add_up_past_the_end_of_the_pool():
    total = speedtest._POOL_BYTES + 3 * speedtest._CHUNK + 17
    assert sum(len(p) for p in speedtest._chunks(total)) == total


def test_upload_counts_what_arrived_and_ping_answers(client):
    h = _login(client)
    res = client.post("/api/network/speedtest/upload", content=b"x" * 300_000, headers=h)
    assert res.status_code == 200
    assert res.json()["bytes"] == 300_000 and res.json()["seconds"] >= 0
    assert client.get("/api/network/speedtest/ping", headers=h).json()["time"] > 0
