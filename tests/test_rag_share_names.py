"""Kib's search index names the shared folder a file is in, as the search compares it with the
person's shares: on Kiboto OS a share is /mnt/storage/<pool>/<share>, and the index named the pool."""

from backend.services import rag_engine, share_access


def test_a_share_on_kiboto_os_is_named_by_its_own_folder(monkeypatch):
    monkeypatch.setattr(
        share_access,
        "known_shares",
        lambda: [
            {"name": "Family Files", "path": "/mnt/storage/tank/family"},
            {"name": "films", "path": "/mnt/storage/tank"},  # a share that is a whole pool
        ],
    )
    assert rag_engine.classify_path_rbac("/mnt/storage/tank/family/taxes.pdf") == ("public_share", "", "family", "*")
    assert rag_engine.classify_path_rbac("/mnt/storage/tank/other/x.txt")[2] == "tank"
    assert rag_engine.classify_path_rbac("/mnt/storage/tank/homes/ana/diary.txt") == (
        "user_home",
        "ana",
        "homes",
        "ana",
    )


def test_without_a_listed_share_the_old_reading_stays(monkeypatch):
    monkeypatch.setattr(share_access, "known_shares", lambda: [])
    assert rag_engine.classify_path_rbac("/mnt/user/films/a.mkv")[2] == "films"
    assert rag_engine.classify_path_rbac("/boot/config/go")[0] == "admin_boot"

    def broken():
        raise RuntimeError("no storage platform")

    monkeypatch.setattr(share_access, "known_shares", broken)
    assert rag_engine.classify_path_rbac("/mnt/user/music/a.flac")[2] == "music"
