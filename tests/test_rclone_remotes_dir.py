"""On Kiboto OS the web process does not make the folder cloud drives are mounted in: the host
door does, when it mounts one (the web user may not write to /mnt)."""

from backend import runtime
from backend.services import rclone_engine


def _engine(tmp_path, monkeypatch, without_root):
    monkeypatch.setattr(runtime, "without_root", lambda: without_root)
    e = rclone_engine.RcloneEngine.__new__(rclone_engine.RcloneEngine)
    e.config_file = str(tmp_path / "rclone" / "rclone.conf")
    e.cache_dir = str(tmp_path / "cache")
    e.remotes_dir = str(tmp_path / "remotes")
    e._ensure_directories()
    return tmp_path


def test_the_door_makes_the_remotes_folder_on_kiboto_os(tmp_path, monkeypatch):
    made = _engine(tmp_path, monkeypatch, True)
    assert (made / "rclone").is_dir() and (made / "cache").is_dir() and not (made / "remotes").exists()


def test_elsewhere_kiboto_makes_it(tmp_path, monkeypatch):
    assert (_engine(tmp_path, monkeypatch, False) / "remotes").is_dir()
