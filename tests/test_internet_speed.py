"""The internet speed test (owner, 19 Nov 2026): off by default, runs only on the button."""

import httpx
import pytest

from backend import outside_checks
from backend.services import internet_speed


@pytest.fixture(autouse=True)
def fresh_state(tmp_path, monkeypatch):
    monkeypatch.setattr(outside_checks, "STATE_FILE", str(tmp_path / "outside_checks.json"))
    monkeypatch.setattr(internet_speed, "RESULT_FILE", str(tmp_path / "internet_speed.json"))


def _client(seen, fail=False):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.url.params.get("bytes"), len(request.content)))
        if fail:
            return httpx.Response(503)
        if request.method == "POST":
            return httpx.Response(200, text="ok")
        size = int(request.url.params.get("bytes") or 0)
        return httpx.Response(200, content=b"x" * min(size, 2_000_000))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_off_by_default_nothing_is_asked():
    seen = []
    assert internet_speed.view() == {"enabled": False, "last": None}
    with pytest.raises(internet_speed.TurnedOff):
        internet_speed.measure(_client(seen))
    assert seen == []


def test_it_measures_both_directions_and_the_answer_time_and_keeps_the_result():
    outside_checks.set_enabled("internet_speed", True)
    seen = []
    out = internet_speed.measure(_client(seen), now=lambda: 1763500000)
    assert out["measured_at"] == 1763500000
    assert out["down_mbit"] > 0 and out["up_mbit"] > 0 and out["answer_ms"] >= 0
    assert [s[:3] for s in seen[:3]] == [("GET", "/__down", "0")] * 3
    assert seen[3][:3] == ("GET", "/__down", str(internet_speed.DOWN_BYTES))
    assert seen[4][0] == "POST" and seen[4][1] == "/__up" and seen[4][3] == internet_speed.UP_BYTES
    assert internet_speed.view() == {"enabled": True, "last": out}


def test_the_download_stops_at_its_time_limit():
    ticks = iter([0.0, 9.0, 9.0])
    seen = []
    mbit = internet_speed._download(_client(seen), clock=lambda: next(ticks), limit=8.0)
    assert mbit > 0  # one piece arrived before the limit was reached


def test_one_at_a_time_and_a_service_that_fails():
    outside_checks.set_enabled("internet_speed", True)
    assert internet_speed._running.acquire(blocking=False)
    try:
        with pytest.raises(internet_speed.Busy):
            internet_speed.measure(_client([]))
    finally:
        internet_speed._running.release()
    with pytest.raises(httpx.HTTPError):
        internet_speed.measure(_client([], fail=True))
    assert internet_speed._running.acquire(blocking=False)  # released after a failure
    internet_speed._running.release()
    assert internet_speed.last() is None


def test_the_routes(client, monkeypatch):
    assert client.get("/api/network/speedtest/internet").status_code in (401, 403)
    h = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'password': 'admin'}).json()['token']}"}
    assert client.get("/api/network/speedtest/internet", headers=h).json() == {"enabled": False, "last": None}
    res = client.post("/api/network/speedtest/internet", headers=h)
    assert res.status_code == 409 and res.json()["error"] == "turned_off"
    outside_checks.set_enabled("internet_speed", True)
    result = {"answer_ms": 12.0, "down_mbit": 250.0, "up_mbit": 40.0, "measured_at": 1}
    monkeypatch.setattr(internet_speed, "measure", lambda: result)
    assert client.post("/api/network/speedtest/internet", headers=h).json() == result

    def busy():
        raise internet_speed.Busy("A speed test is already running.")

    monkeypatch.setattr(internet_speed, "measure", busy)
    assert client.post("/api/network/speedtest/internet", headers=h).status_code == 409

    def down():
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(internet_speed, "measure", down)
    res = client.post("/api/network/speedtest/internet", headers=h)
    assert res.status_code == 502 and res.json()["error"] == "unreachable"
