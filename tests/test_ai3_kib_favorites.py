"""AI 3: Kib's favourites are each person's own; the old shared list goes to an administrator once."""

from types import SimpleNamespace

import pytest

from backend import config
from backend.services import kib_favorites


def _who(name, admin=False):
    return SimpleNamespace(username=name, has_scope=lambda s: admin)


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))


class _Rag:
    """Only the parts my_favorites and toggle_favorite use."""

    def __init__(self, shared):
        self.cfg = {"favorites": list(shared)}

    def get_config(self):
        return dict(self.cfg)

    def update_config(self, updates):
        self.cfg.update(updates)
        return dict(self.cfg)


def _engine(shared=()):
    from backend.services.rag_engine_learning import RagLearningMixin

    rag = _Rag(shared)
    rag.my_favorites = RagLearningMixin.my_favorites.__get__(rag)
    rag.toggle_favorite = RagLearningMixin.toggle_favorite.__get__(rag)
    return rag


def test_one_persons_star_is_not_anothers():
    rag = _engine()
    assert rag.toggle_favorite("/mnt/user/a.pdf", _who("ana"))["is_favorite"] is True
    assert rag.my_favorites(_who("ana")) == ["/mnt/user/a.pdf"]
    assert rag.my_favorites(_who("ben")) == []
    assert rag.toggle_favorite("/mnt/user/a.pdf", _who("ana"))["is_favorite"] is False
    assert rag.my_favorites(_who("ana")) == []


def test_the_shared_list_goes_to_the_first_administrator_once():
    rag = _engine(["/mnt/user/old.pdf"])
    assert rag.my_favorites(_who("kid")) == []  # not an administrator: the shared list stays put
    assert rag.cfg["favorites"] == ["/mnt/user/old.pdf"]
    assert rag.my_favorites(_who("owner", admin=True)) == ["/mnt/user/old.pdf"]
    assert rag.cfg["favorites"] == []
    assert rag.my_favorites(_who("other", admin=True)) == []


def test_nobody_known_has_no_favourites():
    assert kib_favorites.load(None) == []
    with pytest.raises(ValueError):
        kib_favorites.toggle(None, "/x")
    kib_favorites.adopt_shared(None, ["/x"])
    kib_favorites.adopt_shared(_who("a"), [])
    assert kib_favorites.load(_who("a")) == []


def test_a_broken_file_starts_empty_and_names_are_case_blind(tmp_path):
    (tmp_path / "kib_favorites.json").write_text("[1, 2]")
    assert kib_favorites.load(_who("Ana")) == []
    kib_favorites.toggle(_who("Ana"), "/x")
    assert kib_favorites.load(_who("ana")) == ["/x"]
    (tmp_path / "kib_favorites.json").write_text("[]")
    kib_favorites.adopt_shared(_who("ana"), ["/y", 3])
    assert kib_favorites.load(_who("ana")) == ["/y"]


def test_the_route_keeps_each_persons_list(client, auth_headers, monkeypatch, tmp_path):
    rag = _engine()
    monkeypatch.setattr("backend.api.media.get_rag_engine", lambda: rag)
    monkeypatch.setattr("backend.api.media._validate_media_path", lambda p, pr, must_exist=False: p)
    res = client.post("/api/ai/favorites", json={"path": "/mnt/user/b.pdf"}, headers=auth_headers)
    assert res.status_code == 200 and res.json()["is_favorite"] is True
    monkeypatch.setattr(rag, "toggle_favorite", lambda p, pr: (_ for _ in ()).throw(ValueError("sign in")))
    assert client.post("/api/ai/favorites", json={"path": "/x"}, headers=auth_headers).status_code == 400
