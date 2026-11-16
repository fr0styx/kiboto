"""SET-28 Files 2: Organize Media never replaces a file already at the target, and a link that
cannot be made is a failure with a reason, not a quiet move."""

import os

import pytest

from backend.services import media_organizer as mo


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setattr(mo, "_get_allowed_media_roots", lambda: [str(tmp_path)])
    src = tmp_path / "in"
    dst = tmp_path / "out"
    src.mkdir()
    dst.mkdir()
    return src, dst


def _item(src, dst):
    return {"source_path": str(src), "destination_path": str(dst)}


@pytest.mark.parametrize("action,hardlink", [("move", False), ("copy", False), ("copy", True)])
def test_a_film_already_there_is_kept(roots, action, hardlink):
    src, dst = roots
    film = src / "Film.2020.mkv"
    film.write_text("new")
    target = dst / "Movies" / "Film (2020)" / "Film (2020).mkv"
    target.parent.mkdir(parents=True)
    target.write_text("the one the family kept")
    res = mo.apply_organize([_item(film, target)], action=action, hardlink=hardlink)
    assert target.read_text() == "the one the family kept"
    assert film.read_text() == "new"  # nothing moved away either
    assert res["kept_count"] == 1 and res["success_count"] == 0 and res["status"] == "partial"


def test_move_copy_and_link_still_work(roots):
    src, dst = roots
    a, b, c = (src / n for n in ("a.mkv", "b.mkv", "c.mkv"))
    for f in (a, b, c):
        f.write_text(f.name)
    ta, tb, tc = (dst / "x" / n for n in ("a.mkv", "b.mkv", "c.mkv"))
    res = mo.apply_organize([_item(a, ta)], action="move")
    assert res["success_count"] == 1 and not a.exists() and ta.read_text() == "a.mkv"
    res = mo.apply_organize([_item(b, tb)], action="copy")
    assert res["success_count"] == 1 and b.exists() and tb.read_text() == "b.mkv"
    res = mo.apply_organize([_item(c, tc)], action="copy", hardlink=True)
    assert res["success_count"] == 1 and c.exists() and os.path.samefile(c, tc)
    assert res["status"] == "ok" and res["kept_count"] == 0


def test_a_link_that_cannot_be_made_moves_nothing(roots, monkeypatch):
    src, dst = roots
    film = src / "f.mkv"
    film.write_text("seeding")

    def no_link(a, b):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(mo.os, "link", no_link)
    res = mo.apply_organize([_item(film, dst / "f.mkv")], action="copy", hardlink=True)
    assert film.read_text() == "seeding" and not (dst / "f.mkv").exists()
    assert res["failed_count"] == 1 and res["failures"][0]["code"] == "no_link"


def test_a_move_to_another_drive_copies_then_removes(roots, monkeypatch):
    src, dst = roots
    film = src / "g.mkv"
    film.write_text("film")

    def no_link(a, b):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(mo.os, "link", no_link)
    res = mo.apply_organize([_item(film, dst / "y" / "g.mkv")], action="move")
    assert res["success_count"] == 1 and not film.exists() and (dst / "y" / "g.mkv").read_text() == "film"


def test_a_file_appearing_at_the_last_moment_is_kept(roots, monkeypatch):
    src, dst = roots
    film = src / "h.mkv"
    film.write_text("new")
    target = dst / "h.mkv"

    def racing_link(a, b):
        target.write_text("arrived first")
        raise FileExistsError(b)

    monkeypatch.setattr(mo.os, "link", racing_link)
    res = mo.apply_organize([_item(film, target)], action="move")
    assert target.read_text() == "arrived first" and film.exists() and res["kept_count"] == 1
