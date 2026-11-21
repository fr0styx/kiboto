"""A new Kiboto version on a machine it runs on without a container: made ready beside the running
one from the same signed image, switched by a helper that outlives the restart, and switched back,
with the data as it was, when the new version does not hold."""

import io
import json
import os
import tarfile

import pytest

from backend.services import docker_client
from backend.services import native_update as nu


def tar_of(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


IMAGE = {
    "backend": tar_of({"backend/__init__.py": b'__version__ = "9.9.9"\n', "backend/main.py": b"print('hi')\n"}),
    "static": tar_of({"static/index.html": b"<html></html>"}),
    "app.py": tar_of({"app.py": b"# app\n"}),
    "requirements.lock": tar_of({"requirements.lock": b"fastapi==1 --hash=sha256:aa\n"}),
}


class Docker:
    """Stands in for Docker: an image whose /app holds `parts`."""

    def __init__(self, monkeypatch, parts=None, created=201):
        self.parts = dict(IMAGE if parts is None else parts)
        self.created = created
        self.asked = []
        monkeypatch.setattr(docker_client, "request", self.request)
        monkeypatch.setattr(docker_client, "raw_request", self.raw)

    def request(self, method, path, body=None, **k):
        self.asked.append((method, path))
        if path == "/containers/create":
            assert body["Cmd"] == ["true"] and body["NetworkDisabled"] is True  # nothing of the image runs
            return self.created, {"Id": "c1"}
        if method == "GET":
            return 200, {
                "Config": {"Env": ["PATH=/usr/bin", "BUILD_COMMIT=abc1234", "BUILD_DATE=2026-11-21", "SECRET=x"]}
            }
        return 204, None

    def raw(self, method, path, body=None, **k):
        part = path.split("%2Fapp%2F")[-1].split("/app/")[-1]
        return (200, self.parts[part]) if part in self.parts else (404, b"")


def test_the_environment_is_named_by_its_requirements(tmp_path):
    a, b = tmp_path / "a.lock", tmp_path / "b.lock"
    a.write_text("x==1\n")
    b.write_text("x==2\n")
    assert nu.lock_key(str(a)) == nu.lock_key(str(a)) != nu.lock_key(str(b))
    assert len(nu.lock_key(str(a))) == 16


def test_kibotos_files_are_copied_out_of_the_image_and_nothing_runs(tmp_path, monkeypatch):
    docker = Docker(monkeypatch)
    build = nu.extract("ghcr.io/x/kiboto@sha256:1", str(tmp_path / "rel"))
    assert build == {"BUILD_COMMIT": "abc1234", "BUILD_DATE": "2026-11-21"}  # nothing else of its environment
    assert (tmp_path / "rel" / "backend" / "main.py").read_text() == "print('hi')\n"
    assert (tmp_path / "rel" / "static" / "index.html").exists() and (tmp_path / "rel" / "requirements.lock").exists()
    assert (tmp_path / "rel" / "build.env").read_text() == "BUILD_COMMIT=abc1234\nBUILD_DATE=2026-11-21\n"
    assert docker.asked[-1] == ("DELETE", "/containers/c1?force=true")
    assert not [a for a in docker.asked if "/start" in a[1]]


def test_an_image_that_is_not_kiboto_is_refused_and_cleaned_up(tmp_path, monkeypatch):
    docker = Docker(monkeypatch, parts={"backend": IMAGE["backend"]})
    with pytest.raises(nu.UpdateFailed, match="has no static"):
        nu.extract("img", str(tmp_path / "rel"))
    assert docker.asked[-1] == ("DELETE", "/containers/c1?force=true")
    Docker(monkeypatch, created=404)
    with pytest.raises(nu.UpdateFailed, match="could not be opened"):
        nu.extract("img", str(tmp_path / "rel2"))


class Runs:
    """Pretend commands: `python -m venv <dir>` makes the folder; `fail` names a word that fails."""

    def __init__(self):
        self.ran = []
        self.fail = None

    def __call__(self, cmd, timeout=60, cwd=None, env=None):
        self.ran.append(cmd)
        if self.fail and self.fail in " ".join(cmd):
            return 1, "it did not work"
        if cmd[1:3] == ["-m", "venv"]:
            os.makedirs(os.path.join(cmd[-1], "bin"), exist_ok=True)
            with open(os.path.join(cmd[-1], "bin", "python"), "w") as f:
                f.write("")
        return 0, ""

    def did(self, word):
        return [c for c in self.ran if word in " ".join(c)]


def _release(tmp_path, name, lock="x==1\n"):
    rel = tmp_path / "releases" / name
    rel.mkdir(parents=True)
    (rel / "requirements.lock").write_text(lock)
    return str(rel)


def test_versions_with_the_same_requirements_share_one_environment(tmp_path):
    run = Runs()
    one, two = _release(tmp_path, "one"), _release(tmp_path, "two")
    venv = nu.venv_for(one, str(tmp_path), run)
    assert os.path.realpath(os.path.join(one, "venv")) == os.path.realpath(venv)
    assert len(run.did("pip")) == 1 and "--require-hashes" in run.did("pip")[0]
    assert nu.venv_for(two, str(tmp_path), run) == venv and len(run.did("pip")) == 1  # nothing installed again
    other = _release(tmp_path, "three", lock="x==2\n")
    assert nu.venv_for(other, str(tmp_path), run) != venv and len(run.did("pip")) == 2


def test_an_environment_that_was_not_finished_is_made_again(tmp_path):
    run = Runs()
    rel = _release(tmp_path, "one")
    run.fail = "pip"
    with pytest.raises(nu.UpdateFailed, match="Python packages could not be installed"):
        nu.venv_for(rel, str(tmp_path), run)
    assert not os.listdir(tmp_path / "venvs")
    half = tmp_path / "venvs" / nu.lock_key(os.path.join(rel, "requirements.lock"))
    (half / "bin").mkdir(parents=True)  # a power cut during an earlier try
    run.fail = None
    nu.venv_for(rel, str(tmp_path), run)
    assert (half / ".ready").exists() and len(run.did("pip")) == 2


def test_the_new_version_is_made_ready_or_leaves_nothing(tmp_path, monkeypatch):
    Docker(monkeypatch)
    run = Runs()
    rel = nu.prepare("img", "9.9.9", str(tmp_path), run)
    assert os.path.basename(rel).startswith("9.9.9-") and os.path.islink(os.path.join(rel, "venv"))
    assert run.did("import backend.runtime")  # it loads on this machine before anything is switched
    run.fail = "import backend.runtime"
    with pytest.raises(nu.UpdateFailed, match="does not load here"):
        nu.prepare("img", "9.9.10", str(tmp_path), run)
    assert [n for n in os.listdir(tmp_path / "releases")] == [os.path.basename(rel)]
    Docker(
        monkeypatch,
        parts={"backend": tar_of({"../outside.py": b"x"}), **{k: v for k, v in IMAGE.items() if k != "backend"}},
    )
    with pytest.raises(nu.UpdateFailed):
        nu.prepare("img", "9.9.11", str(tmp_path), Runs())
    assert not (tmp_path / "outside.py").exists() and not (tmp_path / "releases" / "outside.py").exists()


def test_switching_is_one_step_and_remembers_the_version_before(tmp_path):
    a, b = _release(tmp_path, "a"), _release(tmp_path, "b")
    assert nu.point_at(a, str(tmp_path)) == ""
    assert os.path.realpath(tmp_path / "current") == os.path.realpath(a) and not (tmp_path / "previous").exists()
    assert nu.point_at(b, str(tmp_path)) == os.path.realpath(a)
    assert os.path.realpath(tmp_path / "current") == os.path.realpath(b)
    assert (tmp_path / "previous").read_text().strip() == os.path.realpath(a)
    assert nu.point_at(b, str(tmp_path)) == os.path.realpath(b)  # the same again changes nothing
    assert (tmp_path / "previous").read_text().strip() == os.path.realpath(a)


def _health(monkeypatch, answers):
    answers = list(answers)

    class Res:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return io.StringIO(json.dumps(self.body))

        def __exit__(self, *a):
            return False

    def urlopen(url, timeout=5):
        a = answers.pop(0) if len(answers) > 1 else answers[0]
        if a is None:
            raise OSError("connection refused")
        return Res({"status": a})

    monkeypatch.setattr(nu.urllib.request, "urlopen", urlopen)


def test_healthy_means_ok_and_staying_ok(monkeypatch):
    _health(monkeypatch, [None, "starting", "ok"])
    assert nu.healthy(8082, timeout=5, dwell=0, sleep=lambda s: None) == (True, "ok for 0 s")
    _health(monkeypatch, ["ok", "degraded"])
    assert nu.healthy(8082, timeout=5, dwell=60, sleep=lambda s: None) == (
        False,
        "the app reported a failed part (degraded)",
    )
    _health(monkeypatch, [None])
    assert nu.healthy(8082, timeout=0.05, dwell=0, sleep=lambda s: None) == (False, "the new version did not answer")
    _health(monkeypatch, [None])
    crash_loop = nu.healthy(8082, timeout=30, dwell=0, sleep=lambda s: None, stopped=lambda: 3)
    assert crash_loop == (False, "the new version stops as soon as it starts")  # no need to wait the whole time
    assert nu.restarts(lambda cmd, timeout=10: (0, "4")) == 4 and nu.restarts(lambda cmd, timeout=10: (1, "")) == 0
    _health(monkeypatch, ["starting"])
    assert nu.healthy(8082, timeout=0.05, dwell=0, sleep=lambda s: None)[1] == "the new version did not report ok"


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A machine running version `a` with `b` made ready; records what the helper does."""
    a, b = _release(tmp_path, "a"), _release(tmp_path, "b")
    nu.point_at(a, str(tmp_path))
    data = tmp_path / "data"
    data.mkdir()
    steps = []
    results = []
    from backend.services import data_snapshot, self_updater

    monkeypatch.setattr(
        data_snapshot, "take_snapshot", lambda d, **k: steps.append("snapshot") or str(tmp_path / "snap")
    )
    monkeypatch.setattr(data_snapshot, "restore_snapshot", lambda s, d: steps.append("restore") or [])
    monkeypatch.setattr(
        self_updater, "write_update_result", lambda d, result, why="", **k: results.append((result, why))
    )

    def run(cmd, timeout=60, cwd=None, env=None):
        if cmd[1] == "show":
            return 0, "0"
        steps.append(
            " ".join(cmd[:2])
            + (":" + os.path.basename(os.path.realpath(tmp_path / "current")) if cmd[1] == "start" else "")
        )
        return 0, ""

    return {"prefix": str(tmp_path), "a": a, "b": b, "data": str(data), "steps": steps, "results": results, "run": run}


def test_the_helper_switches_and_keeps_the_new_version_when_it_holds(machine, monkeypatch):
    monkeypatch.setattr(nu, "healthy", lambda port, **k: (True, "ok for 20 s"))
    assert nu.apply(machine["b"], machine["data"], 8082, "img", machine["prefix"], machine["run"]) == "updated"
    assert machine["steps"] == ["systemctl stop", "snapshot", "systemctl start:b"]  # data saved while nothing runs
    assert machine["results"] == [("updated", "ok for 20 s")]
    assert os.path.realpath(os.path.join(machine["prefix"], "current")) == os.path.realpath(machine["b"])


def test_a_version_that_does_not_hold_is_taken_back_with_the_data_as_it_was(machine, monkeypatch):
    monkeypatch.setattr(nu, "healthy", lambda port, **k: (False, "the new version did not answer"))
    assert nu.apply(machine["b"], machine["data"], 8082, "img", machine["prefix"], machine["run"]) == "rolled_back"
    assert machine["steps"] == [
        "systemctl stop",
        "snapshot",
        "systemctl start:b",
        "systemctl stop",
        "restore",
        "systemctl reset-failed",
        "systemctl start:a",
    ]
    assert machine["results"] == [("rolled_back", "the new version did not answer")]
    assert os.path.realpath(os.path.join(machine["prefix"], "current")) == os.path.realpath(machine["a"])
    assert not os.path.exists(machine["b"])  # the version that failed is removed
    assert not os.path.exists(os.path.join(machine["prefix"], "previous"))  # and is nobody's previous version


def test_without_a_snapshot_nothing_is_switched(machine, monkeypatch):
    from backend.services import data_snapshot

    def full(d, **k):
        raise OSError("No space left on device")

    monkeypatch.setattr(data_snapshot, "take_snapshot", full)
    assert nu.apply(machine["b"], machine["data"], 8082, "img", machine["prefix"], machine["run"]) == "not_applied"
    assert machine["steps"] == ["systemctl stop", "systemctl start:a"]
    assert machine["results"][0][0] == "not_applied" and "No space left" in machine["results"][0][1]


def test_data_that_cannot_be_put_back_is_said(machine, monkeypatch):
    from backend.services import data_snapshot

    def broken(s, d):
        raise OSError("read error")

    monkeypatch.setattr(nu, "healthy", lambda port, **k: (False, "it did not report ok"))
    monkeypatch.setattr(data_snapshot, "restore_snapshot", broken)
    assert nu.apply(machine["b"], machine["data"], 8082, "img", machine["prefix"], machine["run"]) == "rolled_back"
    assert "the earlier data could not be put back: read error" in machine["results"][0][1]


def test_old_versions_go_but_never_the_current_or_the_previous(tmp_path):
    rels = [_release(tmp_path, f"v{i}") for i in range(6)]
    for i, r in enumerate(rels):
        os.utime(r, (1000 + i, 1000 + i))
    nu.point_at(rels[0], str(tmp_path))  # an old one is still the previous version
    nu.point_at(rels[5], str(tmp_path))
    nu.prune(str(tmp_path), keep=2)
    assert sorted(os.listdir(tmp_path / "releases")) == ["v0", "v4", "v5"]
    nu.prune(str(tmp_path / "nothing-here"))  # no folder: nothing to do


def test_the_switch_is_handed_to_a_helper_that_outlives_the_restart(tmp_path, monkeypatch):
    Docker(monkeypatch)
    nu.point_at(_release(tmp_path, "a"), str(tmp_path))
    run = Runs()
    rel = nu.start("img@sha256:1", "9.9.9", "/var/lib/kiboto", 8082, str(tmp_path), run)
    cmd = run.did("systemd-run")[0]
    assert cmd[cmd.index("-m") :] == [
        "-m",
        "backend.services.native_update",
        "apply",
        rel,
        "/var/lib/kiboto",
        "8082",
        "img@sha256:1",
    ]
    assert "--collect" in cmd and any(a.startswith("--unit") or a == "--unit" for a in cmd)
    assert os.path.realpath(tmp_path / "current").endswith("/a")  # nothing switched yet: the helper does that
    run.fail = "systemd-run"
    with pytest.raises(nu.UpdateFailed, match="could not be handed over"):
        nu.start("img", "9.9.10", "/var/lib/kiboto", 8082, str(tmp_path), run)
    assert len(os.listdir(tmp_path / "releases")) == 2  # a and the first new one; the refused one is gone


def test_the_helpers_entry(monkeypatch, capsys):
    monkeypatch.setattr(nu.time, "sleep", lambda s: None)
    seen = []
    monkeypatch.setattr(
        nu, "apply", lambda rel, data, port, image="": seen.append((rel, data, port, image)) or "updated"
    )
    assert nu.main(["x", "apply", "/opt/kiboto/releases/b", "/var/lib/kiboto", "8082", "img"]) == 0
    assert seen == [("/opt/kiboto/releases/b", "/var/lib/kiboto", 8082, "img")]
    monkeypatch.setattr(nu, "apply", lambda *a: "rolled_back")
    assert nu.main(["x", "apply", "r", "d", "8082"]) == 1
    assert nu.main(["x"]) == 2 and "usage" in capsys.readouterr().out


def test_the_runner_answers_for_a_missing_or_stuck_tool():
    assert nu._run(["true"]) == (0, "")
    assert nu._run(["no-such-tool-kb"])[0] == 127
    assert nu._run(["sleep", "5"], timeout=0.2)[0] == 124
