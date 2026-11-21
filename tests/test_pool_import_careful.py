"""A pool from elsewhere is looked at before it is changed.

import_pool ran `zpool import -f <name>`: read-write at once, by a name two pools can share, and
with the force that passes ZFS's own "another system has this pool" refusal. A ZFS pool Kiboto does
not know is now imported read-only and by its id; force is used only when the person said so after
that refusal; and the pool becomes one of this system's only when changes are allowed."""

import pytest

from backend.hardware.pal import pool_registry as reg
from backend.hardware.pal.base import PoolUsedElsewhere, StoragePool
from backend.hardware.pal_storage import GenericLinuxStorageAdapter

ELSEWHERE = (
    1,
    "",
    "cannot import 'tank': pool was previously in use from another system.\n"
    "Last accessed by oldnas (hostid=8a3c11) at Sat Nov 14 2026\n"
    "The pool can be imported, use 'zpool import -f' to import the pool.\n",
)
LOOK = ["zpool", "import", "-o", "readonly=on", "-o", "cachefile=none"]


class Tools:
    def __init__(self):
        self.ran = []
        self.answers = {}

    def __call__(self, cmd):
        self.ran.append(cmd)
        for start, answer in self.answers.items():
            if " ".join(cmd).startswith(start):
                return answer(cmd) if callable(answer) else answer
        return 0, "", ""

    def did(self, start):
        return [c for c in self.ran if " ".join(c).startswith(start)]


@pytest.fixture
def tools():
    return Tools()


@pytest.fixture
def nas(tmp_path, tools):
    adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path / "pools"))
    adapter._run_cmd = tools
    adapter._discover_hal_disks = lambda: []
    return adapter


def test_an_unknown_pool_is_opened_for_reading_by_its_id(nas, tools):
    res = nas.import_pool("tank", fs_type="zfs", guid="4711")
    assert tools.did("zpool import") == [LOOK + ["4711"]]
    assert res["status"] == "imported" and res["read_only"] is True
    assert reg.find("tank") is None  # not one of this system's pools yet
    nas.import_pool("tank", fs_type="zfs")  # without an id: by its name
    assert tools.did("zpool import")[-1] == LOOK + ["tank"]


def test_a_pool_another_system_had_needs_the_persons_word(nas, tools):
    tools.answers["zpool import"] = lambda cmd: (0, "", "") if "-f" in cmd else ELSEWHERE
    with pytest.raises(PoolUsedElsewhere, match="tank was last used by another system"):
        nas.import_pool("tank", fs_type="zfs", guid="4711")
    assert not [c for c in tools.ran if "-f" in c]
    assert nas.import_pool("tank", fs_type="zfs", guid="4711", force=True)["read_only"] is True
    assert tools.did("zpool import")[-1] == LOOK + ["-f", "4711"]


def test_any_other_refusal_is_said_as_it_is(nas, tools):
    tools.answers["zpool import"] = (1, "", "cannot import 'tank': one or more devices is currently unavailable")
    with pytest.raises(RuntimeError, match="currently unavailable") as e:
        nas.import_pool("tank", fs_type="zfs")
    assert not isinstance(e.value, PoolUsedElsewhere)
    with pytest.raises(RuntimeError, match="currently unavailable"):
        nas.import_pool("tank", fs_type="zfs", force=True)  # force does not turn it into the other question


def test_a_pool_ejected_here_comes_back_as_it_was(nas, tools):
    reg.record("tank", "zfs", "mirror", "4711", [], "/mnt/tank")
    reg.set_ejected("tank", True)
    tools.answers["zpool get -Hp -o value guid"] = (1, "", "no such pool")
    res = nas.import_pool("tank", fs_type="zfs")
    assert tools.did("zpool import") == [["zpool", "import", "4711"]]  # read-write, no force
    assert res["read_only"] is False and reg.find("tank")["ejected"] is False
    tools.answers["zpool import"] = (1, "", "no pools available to import")
    reg.set_ejected("tank", True)
    with pytest.raises(RuntimeError, match="no pools available"):
        nas.import_pool("tank", fs_type="zfs")


def _looked_at(nas, read_only=True):
    pool = StoragePool(
        id="tank", name="tank", pool_type="zfs_mirror", fs_type="zfs", fs_profile="mirror", read_only=read_only
    )
    nas.resolve_pool = lambda pid: pool
    return pool


def test_allowing_changes_reopens_the_pool_and_writes_it_down(nas, tools):
    _looked_at(nas)
    tools.answers["zpool get -Hp -o value guid"] = (0, "4711\n", "")
    tools.answers["zfs get"] = (0, "/mnt/tank\n", "")
    assert nas.allow_changes("tank") == {"status": "writable", "pool_id": "tank"}
    steps = [c for c in tools.ran if c[0] == "zpool" and c[1] in ("export", "import")]
    assert steps == [["zpool", "export", "tank"], ["zpool", "import", "4711"]]
    row = reg.find("tank")
    assert (row["uuid"], row["profile"], row["mountpoint"], row["origin"]) == (
        "4711",
        "mirror",
        "/mnt/tank",
        "imported",
    )


def test_allowing_changes_passes_the_question_already_answered(nas, tools):
    _looked_at(nas)
    tools.answers["zpool get -Hp -o value guid"] = (0, "4711\n", "")
    tools.answers["zpool import"] = lambda cmd: (0, "", "") if "-f" in cmd else ELSEWHERE
    assert nas.allow_changes("tank")["status"] == "writable"
    assert tools.did("zpool import") == [["zpool", "import", "4711"], ["zpool", "import", "-f", "4711"]]


def test_a_pool_that_cannot_be_reopened_stays_as_it_was(nas, tools):
    _looked_at(nas)
    tools.answers["zpool get -Hp -o value guid"] = (0, "4711\n", "")
    tools.answers["zpool export"] = (1, "", "pool is busy")
    with pytest.raises(RuntimeError, match="in use and could not be reopened: pool is busy"):
        nas.allow_changes("tank")
    assert not tools.did("zpool import")
    tools.answers["zpool export"] = (0, "", "")
    tools.answers["zpool import 4711"] = (1, "", "I/O error")
    with pytest.raises(RuntimeError, match="could not be opened for changes: I/O error"):
        nas.allow_changes("tank")
    assert tools.did("zpool import")[-1] == LOOK + ["-f", "4711"]  # back to reading only
    assert reg.find("tank") is None


def test_a_pool_that_takes_changes_already_is_left_alone(nas, tools):
    _looked_at(nas, read_only=False)
    assert nas.allow_changes("tank") == {"status": "unchanged", "pool_id": "tank"}
    assert tools.ran == []


def test_the_list_says_which_pool_is_only_being_read(nas, tools):
    nas._parse_mdstat = lambda: {}
    nas._parse_mounts = lambda: []
    nas._parse_zpool_members = lambda name: []
    tools.answers["zpool list"] = (0, "tank\t100\t10\t90\tONLINE\nvault\t100\t10\t90\tONLINE\n", "")
    tools.answers["zpool get -H -o value readonly"] = lambda cmd: (0, "on\n" if cmd[-1] == "tank" else "off\n", "")
    pools = {p.id: p.read_only for p in nas.list_pools() if p.fs_type == "zfs"}
    assert pools == {"tank": True, "vault": False}


# ---- the routes


@pytest.fixture
def routed(client, auth_headers, monkeypatch, nas):
    monkeypatch.setattr("backend.api.storage.get_storage_platform", lambda: nas)
    return client, auth_headers


def test_the_import_route_names_the_question(routed, tools):
    client, headers = routed
    tools.answers["zpool import"] = lambda cmd: (0, "", "") if "-f" in cmd else ELSEWHERE
    r = client.post(
        "/api/storage/pools/import", json={"pool_id": "tank", "fs_type": "zfs", "guid": "4711"}, headers=headers
    )
    assert r.status_code == 409 and r.json()["error"] == "pool_used_elsewhere"
    r = client.post(
        "/api/storage/pools/import",
        json={"pool_id": "tank", "fs_type": "zfs", "guid": "4711", "force": True},
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["read_only"] is True
    r = client.post("/api/storage/pools/import", json={"pool_id": "tank", "guid": "not-a-number"}, headers=headers)
    assert r.status_code == 422


def test_the_allow_changes_route(routed, tools, nas, monkeypatch):
    client, headers = routed
    _looked_at(nas)
    tools.answers["zpool get -Hp -o value guid"] = (0, "4711\n", "")
    r = client.post("/api/storage/pools/tank/allow-changes", json={}, headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "writable"
    tools.answers["zpool export"] = (1, "", "pool is busy")
    r = client.post("/api/storage/pools/tank/allow-changes", json={}, headers=headers)
    assert r.status_code == 409 and "pool is busy" in r.json()["detail"]

    def gone(pid):
        raise LookupError("There is no pool “tank” on this system.")

    nas.resolve_pool = gone
    assert client.post("/api/storage/pools/tank/allow-changes", json={}, headers=headers).status_code == 404
    monkeypatch.delattr(GenericLinuxStorageAdapter, "allow_changes")
    assert client.post("/api/storage/pools/tank/allow-changes", json={}, headers=headers).status_code == 403
