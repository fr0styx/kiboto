"""On a machine set up for Kiboto, people's home folders go on the first pool once there is one."""

import os

import pytest

from backend import config, places, runtime
from backend.hardware.pal import pool_registry
from backend.services import pool_places, user_spaces
from backend.users_db import create_user, get_user_by_username, move_unused_homes


@pytest.fixture
def box(tmp_path, monkeypatch):
    mark = tmp_path / "managed"
    mark.write_text("x")
    monkeypatch.setattr(runtime, "CONTAINER_MARKS", (str(tmp_path / "none"),))
    monkeypatch.setattr(runtime, "MANAGED_MARK", str(mark))
    monkeypatch.setattr(runtime, "SETTINGS", type("S", (), {"containerized": False})())
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    main = tmp_path / "storage"
    tank = main / "tank"
    tank.mkdir(parents=True)
    monkeypatch.setattr(config, "POOL_PATH", str(main))
    rows = []
    monkeypatch.setattr(pool_registry, "load", lambda: [dict(r) for r in rows])
    real = os.path.ismount
    monkeypatch.setattr(os.path, "ismount", lambda p: str(p) == str(tank) or real(p))
    return type("Box", (), {"main": str(main), "tank": str(tank), "rows": rows})


def test_the_record_and_the_fallback(box):
    assert places.homes_root() == os.path.join(box.main, "homes")
    assert user_spaces.homes_root() == os.path.join(box.main, "homes")
    places.record("homes", "/mnt/storage/tank/homes")
    assert places.homes_root() == "/mnt/storage/tank/homes"
    places.record("other", "relative/is/ignored")
    assert places.recorded("other") == "" and places.recorded("homes") == "/mnt/storage/tank/homes"


def test_unused_home_records_follow_the_first_pool(box):
    old = os.path.join(box.main, "homes")
    create_user("hp_mia", "hp_mia", "long-enough-pass-1", role_id="share_user")
    create_user("hp_ben", "hp_ben", "long-enough-pass-1", role_id="share_user")
    os.makedirs(os.path.join(old, "hp_ben"))
    with open(os.path.join(old, "hp_ben", "notes.txt"), "w") as f:
        f.write("mine")
    assert get_user_by_username("hp_mia")["home_directory"] == os.path.join(old, "hp_mia")
    assert pool_places.settle() == {}  # no pool yet
    box.rows.append({"name": "tank", "mountpoint": box.tank, "ejected": False})
    out = pool_places.settle()
    new = os.path.join(box.tank, "homes")
    assert out["homes"] == new and out["moved"] >= 1
    assert get_user_by_username("hp_mia")["home_directory"] == os.path.join(new, "hp_mia")
    assert get_user_by_username("hp_ben")["home_directory"] == os.path.join(old, "hp_ben")  # it has files
    create_user("hp_zoe", "hp_zoe", "long-enough-pass-1", role_id="share_user")
    assert get_user_by_username("hp_zoe")["home_directory"] == os.path.join(new, "hp_zoe")
    assert pool_places.settle() == {}  # settled once
    assert move_unused_homes("/nowhere", new) == 0


def test_elsewhere_nothing_moves(box, monkeypatch):
    monkeypatch.setattr(runtime, "MANAGED_MARK", os.path.join(box.main, "no-mark"))
    box.rows.append({"name": "tank", "mountpoint": box.tank, "ejected": False})
    assert pool_places.settle() == {} and places.recorded("homes") == ""
