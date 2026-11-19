"""Re-audit R11: coloured labels on files and folders, each person's own."""

import pytest

from backend.api.files import labels


@pytest.fixture
def area(client, tmp_path, monkeypatch):
    monkeypatch.setattr(labels.config, "DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    root = tmp_path / "share"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "tax.pdf").write_bytes(b"x")
    monkeypatch.setattr(labels, "ALLOWED_BROWSE_ROOTS", [str(root)])
    monkeypatch.setattr(labels, "check_user_path_access", lambda *a, **k: None)
    h = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'password': 'admin'}).json()['token']}"}
    return client, h, root


def test_put_a_colour_on_a_file_rename_the_colour_and_take_it_off(area):
    client, h, root = area
    start = client.get("/api/fs/labels", headers=h).json()
    assert start == {"colours": list(labels.COLOURS), "names": {}, "items": {}}
    path = str(root / "docs" / "tax.pdf")
    res = client.put("/api/fs/labels", headers=h, json={"path": path, "colour": "red"})
    assert res.status_code == 200 and res.json()["items"] == {path: "red"}
    res = client.put("/api/fs/labels", headers=h, json={"path": str(root / "docs") + "/", "colour": "blue"})
    assert res.json()["items"][str(root / "docs")] == "blue"  # a folder too; the trailing slash is dropped
    named = client.put("/api/fs/labels/names", headers=h, json={"colour": "red", "name": "  Taxes "}).json()
    assert named["names"] == {"red": "Taxes"}
    assert client.put("/api/fs/labels/names", headers=h, json={"colour": "red", "name": ""}).json()["names"] == {}
    off = client.put("/api/fs/labels", headers=h, json={"path": path, "colour": None}).json()
    assert path not in off["items"] and client.get("/api/fs/labels", headers=h).json()["items"] == off["items"]


def test_what_cannot_be_labelled(area, monkeypatch):
    client, h, root = area
    assert (
        client.put("/api/fs/labels", headers=h, json={"path": str(root / "docs"), "colour": "pink"}).status_code == 400
    )
    assert (
        client.put("/api/fs/labels", headers=h, json={"path": str(root / "gone.txt"), "colour": "red"}).status_code
        == 400
    )
    assert client.put("/api/fs/labels", headers=h, json={"path": "/etc/passwd", "colour": "red"}).status_code == 400
    assert client.put("/api/fs/labels/names", headers=h, json={"colour": "pink", "name": "x"}).status_code == 400
    monkeypatch.setattr(labels, "MAX_ITEMS", 1)
    assert (
        client.put("/api/fs/labels", headers=h, json={"path": str(root / "docs"), "colour": "red"}).status_code == 200
    )
    full = client.put("/api/fs/labels", headers=h, json={"path": str(root / "docs" / "tax.pdf"), "colour": "red"})
    assert full.status_code == 400 and "up to 1" in full.text
    # changing the colour of one already labelled still works at the limit
    assert (
        client.put("/api/fs/labels", headers=h, json={"path": str(root / "docs"), "colour": "green"}).status_code == 200
    )


def test_a_label_follows_a_rename_and_what_is_inside_a_moved_folder(area):
    client, h, root = area
    docs, pdf = str(root / "docs"), str(root / "docs" / "tax.pdf")
    client.put("/api/fs/labels", headers=h, json={"path": docs, "colour": "blue"})
    client.put("/api/fs/labels", headers=h, json={"path": pdf, "colour": "red"})
    user = client.get("/api/auth/me", headers=h).json()
    username = (user.get("user") or user).get("username")
    assert labels.moved(docs, str(root / "papers"), username) == 2
    items = client.get("/api/fs/labels", headers=h).json()["items"]
    assert items == {str(root / "papers"): "blue", str(root / "papers" / "tax.pdf"): "red"}
    assert labels.moved(str(root / "papers"), str(root / "papers"), username) == 0
    assert labels.moved(str(root / "other"), str(root / "x"), username) == 0
    assert labels.moved(docs, str(root / "y"), "someone-else") == 0


def test_damaged_or_foreign_data_is_ignored(area, tmp_path):
    client, h, root = area
    import json

    (tmp_path / "data" / "fm_labels.json").write_text(
        json.dumps({"admin": {"items": {"/a": "pink"}, "names": "x"}, "other": []})
    )
    assert client.get("/api/fs/labels", headers=h).json()["items"] == {}
    (tmp_path / "data" / "fm_labels.json").write_text("[]")
    assert client.get("/api/fs/labels", headers=h).json()["items"] == {}
    assert labels.moved("/a", "/b", "admin") == 0
