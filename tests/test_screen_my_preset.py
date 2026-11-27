"""#71: "Save as My Preset" is kept with the front-screen layout, and an ordinary save keeps it."""


def test_my_preset_is_kept_until_another_is_saved(client, auth_headers, tmp_path, monkeypatch):
    from backend.api import system

    monkeypatch.setattr(system, "DASH_LAYOUT_FILE", str(tmp_path / "layout.json"))
    mine = {
        "vis": {"metric-cpu": True, "metric-disks": False},
        "order": ["metric-cpu"],
        "sizes": {"metric-cpu": "huge"},
    }
    r = client.post("/api/layout", json={"vis": {"metric-cpu": True}, "my_preset": mine}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["layout"]["my_preset"]["sizes"] == {}  # only full or compact
    r = client.post("/api/layout", json={"vis": {"metric-cpu": False}}, headers=auth_headers)
    assert r.json()["layout"]["my_preset"]["vis"] == {"metric-cpu": True, "metric-disks": False}
