"""The hardware helper is not needed where Kiboto is the machine's own system."""

import pytest

from backend import runtime
from backend.services import hw_helper_container as hw


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    monkeypatch.setattr(hw, "CONFIG_FILE", str(tmp_path / "hw_helper.json"))
    monkeypatch.setattr(hw, "_docker", lambda *a, **k: pytest.fail("no container is asked about"))


def test_natively_it_does_not_apply_and_cannot_be_turned_on(native):
    st = hw.ensure()
    assert st["applies"] is False and st["native"] is True and st["running"] is False
    with pytest.raises(ValueError, match="no container"):
        hw.save(True)
    assert hw.save(False)["enabled"] is False


def test_the_page_is_told_why_it_cannot_be_turned_on(native, client, auth_headers):
    st = client.get("/api/hardware/helper", headers=auth_headers).json()
    assert st["native"] is True and st["applies"] is False
    r = client.put("/api/hardware/helper", headers=auth_headers, json={"enabled": True})  # confirmations pass in tests
    assert r.status_code == 409 and "no container" in r.json()["detail"]
    assert client.put("/api/hardware/helper", headers=auth_headers, json={"enabled": False}).status_code == 200
