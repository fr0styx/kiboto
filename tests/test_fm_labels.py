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


def test_a_label_follows_a_move_but_not_a_copy_or_a_merge(area):
    from backend.services import fs_transfer

    client, h, root = area
    docs, tax = str(root / "docs"), str(root / "docs" / "tax.pdf")
    for p, c in ((docs, "blue"), (tax, "red")):
        assert client.put("/api/fs/labels", headers=h, json={"path": p, "colour": c}).status_code == 200
    (root / "old").mkdir()
    (root / "keep").mkdir()
    (root / "keep" / "docs").mkdir()

    # a copy leaves the label where it was
    carried: list[tuple[str, str]] = []
    fs_transfer.execute_transfer([tax], str(root / "old"), "copy", "merge", carried=carried)
    assert carried == [] and (root / "old" / "tax.pdf").exists()

    # a move into a folder that already holds one by that name is a merge: nothing is told
    fs_transfer.execute_transfer([docs], str(root / "keep"), "move", "merge", carried=carried)
    assert carried == [] and (root / "keep" / "docs" / "tax.pdf").exists()

    # a move to a free name is told, with the new name when one was given
    (root / "keep" / "docs" / "tax.pdf").rename(root / "tax.pdf")
    fs_transfer.execute_transfer(
        [str(root / "tax.pdf")], str(root / "old"), "move", "merge", target_names=["tax 2025.pdf"], carried=carried
    )
    assert carried == [(str(root / "tax.pdf"), str(root / "old" / "tax 2025.pdf"))]
    # something that is not there is an error, not a move
    res = fs_transfer.execute_transfer([str(root / "gone")], str(root / "old"), "move", "merge", carried=carried)
    assert res["status"] == "partial" and len(carried) == 1


def test_the_background_engine_tells_the_labels(area):
    from backend.services import fs_transfer

    client, h, root = area
    assert labels.moved in fs_transfer.MOVED_HOOKS
    user = client.get("/api/auth/me", headers=h).json()
    username = (user.get("user") or user).get("username")
    docs, tax = str(root / "docs"), str(root / "docs" / "tax.pdf")
    for p, c in ((docs, "blue"), (tax, "red")):
        client.put("/api/fs/labels", headers=h, json={"path": p, "colour": c})
    (root / "archive").mkdir()
    carried: list[tuple[str, str]] = []
    fs_transfer.execute_transfer([docs], str(root / "archive"), "move", "merge", carried=carried)
    fs_transfer._tell_moved(carried, username)
    items = client.get("/api/fs/labels", headers=h).json()["items"]
    assert items == {str(root / "archive" / "docs"): "blue", str(root / "archive" / "docs" / "tax.pdf"): "red"}


def test_a_follow_up_that_fails_does_not_fail_the_move(monkeypatch):
    from backend.services import fs_transfer

    seen = []

    def broken(old, new, owner):
        raise OSError("disk full")

    monkeypatch.setattr(fs_transfer, "MOVED_HOOKS", [broken, lambda o, n, w: seen.append((o, n, w))])
    fs_transfer._tell_moved([("/a", "/b")], "ana")
    assert seen == [("/a", "/b", "ana")]
