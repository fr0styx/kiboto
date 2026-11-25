"""GET /media/manifests asks the index as the person: without one the index answers nothing (SEC-37)."""


def test_the_list_asks_as_the_person(client, auth_headers, monkeypatch):
    from backend.services import rag_engine

    seen = {}

    class Engine:
        def list_folder_manifests(self, path_prefix=None, principal=None, limit=100, **kw):
            seen["principal"] = principal
            return [{"folder_path": "/", "files": 3}]

    monkeypatch.setattr(rag_engine, "get_rag_engine", lambda: Engine())
    monkeypatch.setattr("backend.api.media.get_rag_engine", lambda: Engine(), raising=False)
    monkeypatch.setattr("backend.api.fs.user_can_access_path", lambda path, principal: True)
    r = client.get("/api/media/manifests", headers=auth_headers)
    assert r.status_code == 200 and r.json()["count"] == 1
    assert seen["principal"] is not None and getattr(seen["principal"], "username", "")
