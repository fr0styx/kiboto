"""A new Kiboto version on a machine it runs on without a container.

In a container an update swaps the container for one made from the new image. As the service of a
machine there is no container to swap, but the image is still how a version is published, signed
and checked, so the same image is used: Kiboto's own files are copied out of it into a new folder
under /opt/kiboto/releases, a Python environment is made from the locked requirements (kept by the
lock's hash, so versions with the same requirements share one), and the service is pointed at the
new folder and started again.

The switch is done by a helper that outlives the restart (a transient systemd unit running the old
version's code). It stops Kiboto, snapshots the data folder, switches, starts, and waits until the
new version reports "ok" and keeps doing so. If it does not, the helper puts the data and the old
version back and starts that again. `current` and `previous` under /opt/kiboto are the two versions."""

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request
from typing import Any

from backend.config import logger
from backend.services import docker_client

PREFIX = "/opt/kiboto"
PARTS = ("backend", "static", "app.py", "requirements.lock", "packaging")  # /app/<part> in the image
NEEDED = ("backend", "static", "requirements.lock")
BUILD_ENV = ("BUILD_COMMIT", "BUILD_DATE", "KIBOTO_IMAGE_VARIANT")
SERVICE = "kiboto.service"
UNITS = ("kiboto.service", "kiboto-pools.service", "kiboto-door.service")  # packaging/, installed by install.sh
UNIT_DIR = "/etc/systemd/system"
HEALTH_TIMEOUT_SECS = 240
OK_DWELL_SECS = 20
KEEP_RELEASES = 3


class UpdateFailed(RuntimeError):
    """The new version could not be made ready; nothing was switched."""


def _run(
    cmd: list[str], timeout: float = 60, cwd: str | None = None, env: dict[str, str] | None = None
) -> tuple[int, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    except FileNotFoundError:
        return 127, f"{cmd[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]} did not finish in {int(timeout)} s"
    return res.returncode, (res.stderr or res.stdout).strip()[-600:]


def lock_key(lock_path: str) -> str:
    """Names the Python environment a requirements lock gives on this Python."""
    with open(lock_path, "rb") as f:
        digest = hashlib.sha256(f.read() + f"|py{sys.version_info[0]}.{sys.version_info[1]}".encode()).hexdigest()
    return digest[:16]


def extract(image: str, dest: str) -> dict[str, str]:
    """Copies Kiboto's own files out of the image into `dest`. Returns the image's build values.
    Nothing of the image runs: a container is made from it, read and removed."""
    status, made = docker_client.request(
        "POST", "/containers/create", body={"Image": image, "Cmd": ["true"], "NetworkDisabled": True}
    )
    cid = str((made or {}).get("Id") or "") if status == 201 and isinstance(made, dict) else ""
    if not cid:
        raise UpdateFailed(f"the downloaded version could not be opened (Docker answered {status})")
    try:
        os.makedirs(dest, exist_ok=True)
        for part in PARTS:
            st, raw = docker_client.raw_request(
                "GET", f"/containers/{cid}/archive?path={urllib.parse.quote('/app/' + part)}", timeout=300.0
            )
            if st != 200:
                if part in NEEDED:
                    raise UpdateFailed(f"the downloaded version has no {part}")
                continue
            with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
                tar.extractall(dest, filter="data")  # no absolute paths, links out of dest or devices
        st, info = docker_client.request("GET", f"/containers/{cid}/json")
        env = ((info or {}).get("Config") or {}).get("Env") or [] if st == 200 and isinstance(info, dict) else []
        build = {k: v for k, v in (str(e).split("=", 1) for e in env if "=" in str(e)) if k in BUILD_ENV}
        with open(os.path.join(dest, "build.env"), "w", encoding="utf-8") as f:
            f.write("".join(f"{k}={v}\n" for k, v in sorted(build.items())))
        return build
    finally:
        docker_client.request("DELETE", f"/containers/{cid}?force=true")


def venv_for(rel: str, prefix: str = PREFIX, run: Any = None) -> str:
    """The Python environment for this version's requirements, made when no version had them yet.
    One that was not finished (no .ready in it) is made again."""
    run = run or _run
    lock = os.path.join(rel, "requirements.lock")
    venv = os.path.join(prefix, "venvs", lock_key(lock))
    ready = os.path.join(venv, ".ready")
    if not os.path.exists(ready):
        shutil.rmtree(venv, ignore_errors=True)
        os.makedirs(os.path.dirname(venv), exist_ok=True)
        code, said = run([sys.executable, "-m", "venv", venv], timeout=120)
        if code == 0:
            pip = [os.path.join(venv, "bin", "python"), "-m", "pip", "-q", "install", "--no-compile"]
            code, said = run([*pip, "--require-hashes", "-r", lock], timeout=1200)
        if code != 0:
            shutil.rmtree(venv, ignore_errors=True)
            raise UpdateFailed(f"its Python packages could not be installed: {said}")
        with open(ready, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S\n"))
    link = os.path.join(rel, "venv")
    if os.path.islink(link) or os.path.exists(link):
        os.remove(link)
    os.symlink(venv, link)
    return venv


_SHELL_LIST = r'^{name}="((?:[^"\\]|\\\n)*)"'
_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9.+-]+$")


def _shell_list(text: str, name: str) -> list[str]:
    m = re.search(_SHELL_LIST.format(name=name), text, re.M)
    words = m.group(1).replace("\\\n", " ").split() if m else []
    return [w for w in words if _PACKAGE.match(w)]


def tools_of(rel: str) -> list[str]:
    """The machine's packages this version's install script installs (TOOLS in packaging/install.sh),
    less the held ones (HELD), which only the held-set step brings to their tested versions."""
    try:
        with open(os.path.join(rel, "packaging", "install.sh"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    held = set(_shell_list(text, "HELD"))
    return [p for p in _shell_list(text, "TOOLS") if p not in held]


def add_missing_tools(rel: str, run: Any = None) -> list[str]:
    """A newer version can need a package an install made by an older one does not have (hdparm, for
    drive sleep, came with 2.0.6). What is missing is installed from Debian before the switch; when
    that fails the update goes on, and what needs the package says it can't be used. Returns what was
    missing."""
    run = run or _run
    missing = []
    for pkg in tools_of(rel):
        code, said = run(["dpkg-query", "-W", "-f=${Status}", pkg], timeout=20)
        if code != 0 or "ok installed" not in said:
            missing.append(pkg)
    if not missing:
        return []
    apt = ["apt-get", "install", "-y", "-qq", "--no-install-recommends", *missing]
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    code, said = run(apt, timeout=900, env=env)
    if code != 0:  # the package lists may be out of date: once more after reading them again
        run(["apt-get", "update", "-qq"], timeout=300, env=env)
        code, said = run(apt, timeout=900, env=env)
    if code != 0:
        logger.warning("[Update] %s could not be installed, so what needs it waits: %s", " ".join(missing), said)
    else:
        logger.info("[Update] installed what this version needs from Debian: %s", " ".join(missing))
    return missing


def ensure_units(rel: str, run: Any = None, unit_dir: str = UNIT_DIR) -> list[str]:
    """The service files of the running version where an update made by an older one left older
    ones, or none (the host door's came after install.sh had run). The door is (re)started at each
    start of Kiboto, so it runs the same version; Kiboto's own service takes a new file at its
    next start. Returns the files that changed."""
    run = run or _run
    changed = []
    for name in UNITS:
        src = os.path.join(rel, "packaging", name)
        try:
            with open(src, encoding="utf-8") as f:
                want = f.read()
        except OSError:
            continue
        dst = os.path.join(unit_dir, name)
        try:
            with open(dst, encoding="utf-8") as f:
                have = f.read()
        except OSError:
            have = ""
        if have != want:
            with open(dst + ".new", "w", encoding="utf-8") as f:
                f.write(want)
            os.replace(dst + ".new", dst)
            changed.append(name)
    if changed:
        run(["systemctl", "daemon-reload"], timeout=60)
        run(["systemctl", "enable", "-q", *changed], timeout=60)
        logger.info("[Update] service files of this version put in place: %s", " ".join(changed))
    if os.path.exists(os.path.join(unit_dir, "kiboto-door.service")):
        run(["systemctl", "restart", "kiboto-door.service"], timeout=60)
    return changed


def prepare(image: str, version: str, prefix: str = PREFIX, run: Any = None) -> str:
    """Makes the new version ready beside the running one. Returns its folder."""
    run = run or _run
    rel = os.path.join(prefix, "releases", f"{version or 'new'}-{time.strftime('%Y%m%d%H%M%S')}")
    try:
        extract(image, rel)
        venv_for(rel, prefix, run)
        add_missing_tools(rel, run)
        code, said = run(
            [
                os.path.join(rel, "venv", "bin", "python"),
                "-c",
                "import backend.runtime, backend.services.native_update",
            ],
            timeout=120,
            cwd=rel,
            env={**os.environ, "DATA_DIR": os.path.join(rel, ".check")},
        )
        shutil.rmtree(os.path.join(rel, ".check"), ignore_errors=True)
        if code != 0:
            raise UpdateFailed(f"the new version does not load here: {said}")
        rel = _named_by_its_build(rel)
    except (UpdateFailed, OSError, tarfile.TarError, docker_client.DockerError) as e:
        shutil.rmtree(rel, ignore_errors=True)
        raise UpdateFailed(str(e)) from e
    return rel


def _named_by_its_build(rel: str) -> str:
    """The folder takes the name of what it holds, version and build (2.0.5-cdfc428-<when>), so a
    person going back sees which version, not the channel's tag it came by."""
    text = ""
    for part in ("backend/__init__.py", "build.env"):
        try:
            with open(os.path.join(rel, part), encoding="utf-8") as f:
                text += f.read() + "\n"
        except OSError:
            continue
    version = re.search(r'^__version__ = "([0-9A-Za-z.+]+)"', text, re.M)
    commit = re.search(r"^BUILD_COMMIT=([0-9a-f]{7})", text, re.M)
    if not version:
        return rel
    named = os.path.join(
        os.path.dirname(rel),
        "-".join([version.group(1), *([commit.group(1)] if commit else []), time.strftime("%Y%m%d%H%M%S")]),
    )
    if os.path.exists(named):
        return rel
    os.rename(rel, named)  # its venv link points into venvs/ by full path and still holds
    return named


def point_at(rel: str, prefix: str = PREFIX) -> str:
    """Makes `rel` the version the service starts. Returns the folder it started before ('' if none)."""
    current = os.path.join(prefix, "current")
    before = os.path.realpath(current) if os.path.islink(current) else ""
    swap = current + ".new"
    if os.path.islink(swap):
        os.remove(swap)
    os.symlink(rel, swap)
    os.replace(swap, current)  # one step: there is always a version to start
    if before and before != rel:
        with open(os.path.join(prefix, "previous"), "w", encoding="utf-8") as f:
            f.write(before + "\n")
    return before


def restarts(run: Any = None) -> int:
    """How often systemd has started the service again since it was last started by hand."""
    code, said = (run or _run)(["systemctl", "show", SERVICE, "-p", "NRestarts", "--value"], timeout=10)
    return int(said) if code == 0 and said.strip().isdigit() else 0


def healthy(
    port: int,
    timeout: float = HEALTH_TIMEOUT_SECS,
    dwell: float = OK_DWELL_SECS,
    sleep: Any = time.sleep,
    stopped: Any = None,
) -> tuple[bool, str]:
    """True once the app itself reports "ok" and keeps doing so for `dwell` seconds. `stopped`
    says how often the service has stopped and been started again: three times is an answer."""
    deadline = time.time() + timeout
    good_since: float | None = None
    said = "the new version did not answer"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as r:  # noqa: S310 (this machine)
                status = str(json.load(r).get("status") or "")
        except (OSError, ValueError):
            status = ""
        if status == "degraded":
            return False, "the app reported a failed part (degraded)"
        if not status and stopped and stopped() >= 3:
            return False, "the new version stops as soon as it starts"
        if status == "ok":
            good_since = good_since or time.time()
            if time.time() - good_since >= dwell:
                return True, f"ok for {int(dwell)} s"
        else:
            good_since = None
            said = "the new version did not report ok" if status else said
        sleep(2)
    return False, said


def _previous(prefix: str) -> str:
    try:
        with open(os.path.join(prefix, "previous"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _set_previous(prefix: str, rel: str) -> None:
    path = os.path.join(prefix, "previous")
    if rel:
        with open(path, "w", encoding="utf-8") as f:
            f.write(rel + "\n")
    elif os.path.exists(path):
        os.remove(path)


def prune(prefix: str = PREFIX, keep: int = KEEP_RELEASES) -> None:
    """Removes versions older than the newest `keep`, never the current or the previous one."""
    root = os.path.join(prefix, "releases")
    current = os.path.realpath(os.path.join(prefix, "current"))
    previous = _previous(prefix)
    try:
        rels = sorted((os.path.join(root, n) for n in os.listdir(root)), key=os.path.getmtime, reverse=True)
    except OSError:
        return
    for old in rels[keep:]:
        if os.path.realpath(old) not in (current, os.path.realpath(previous) if previous else ""):
            shutil.rmtree(old, ignore_errors=True)


def apply(rel: str, data_dir: str, port: int, image: str = "", prefix: str = PREFIX, run: Any = None) -> str:
    """The helper's work, run outside the service: switch to `rel`, and back if it does not hold.
    Returns "updated", "rolled_back" or "not_applied"."""
    from backend.services.data_snapshot import restore_snapshot, take_snapshot
    from backend.services.self_updater import write_update_result

    run = run or _run
    run(["systemctl", "stop", SERVICE], timeout=180)
    running = os.path.realpath(os.path.join(prefix, "current"))
    try:
        snapshot = take_snapshot(
            data_dir,
            label="before-update",
            # the version this data belongs to: going back takes both together
            extra={"kind": "update", "to": os.path.basename(rel), "from_release": os.path.basename(running)},
        )
    except OSError as e:
        run(["systemctl", "start", SERVICE], timeout=120)
        write_update_result(data_dir, "not_applied", f"could not snapshot the data folder: {e}", to_image=image)
        return "not_applied"
    earlier = _previous(prefix)
    before = point_at(rel, prefix)
    run(["systemctl", "start", SERVICE], timeout=120)
    ok, why = healthy(port, stopped=lambda: restarts(run))
    if ok:
        write_update_result(data_dir, "updated", why, to_image=image)
        prune(prefix)
        return "updated"
    logger.error("[Update] The new version did not hold (%s): going back", why)
    run(["systemctl", "stop", SERVICE], timeout=180)
    try:
        restore_snapshot(snapshot, data_dir)
    except (OSError, ValueError) as e:
        why = f"{why}; the earlier data could not be put back: {e}"
    if before:
        point_at(before, prefix)
        _set_previous(prefix, earlier)  # the version that failed is nobody's "previous"
        shutil.rmtree(rel, ignore_errors=True)
    run(["systemctl", "reset-failed", SERVICE], timeout=30)  # a crash loop may have used up its starts
    run(["systemctl", "start", SERVICE], timeout=120)
    write_update_result(data_dir, "rolled_back", why, to_image=image)
    return "rolled_back"


# --- going back to the version before ---------------------------------------------------------------
def versions_to_go_back_to(data_dir: str, prefix: str = PREFIX) -> list[dict[str, Any]]:
    """The versions this machine can go back to: an update's snapshot whose release is still here,
    with the data as it was before that update. Newest first."""
    from backend.services.data_snapshot import list_snapshots

    current = os.path.basename(os.path.realpath(os.path.join(prefix, "current")))
    out = []
    for snap in list_snapshots(data_dir):
        name = str(snap.get("from_release") or "")
        if snap.get("kind") != "update" or not name or name == current or "/" in name:
            continue
        out.append(
            {
                "id": snap["id"],
                "created_at": snap.get("created_at"),
                "version": _shown(name),
                "image": "",
                "tag": name,
                "image_available": os.path.isdir(os.path.join(prefix, "releases", name)),
            }
        )
    return out


def _shown(name: str) -> str:
    """2.0.5 (cdfc428) for 2.0.5-cdfc428-20261122171949; the first part of an older name."""
    parts = name.split("-")
    if len(parts) >= 3 and re.fullmatch(r"[0-9a-f]{7}", parts[1]):
        return f"{parts[0]} ({parts[1]})"
    return parts[0]


def back(snapshot: str, data_dir: str, port: int, prefix: str = PREFIX, run: Any = None) -> str:
    """The helper's work for going back: the release the snapshot belongs to and the data as it
    was, together. The data of now is saved first. Returns "reverted" or "not_reverted"."""
    from backend.services.data_snapshot import restore_snapshot, take_snapshot
    from backend.services.self_updater import write_update_result

    run = run or _run
    with open(os.path.join(snapshot, "manifest.json"), encoding="utf-8") as f:
        name = str(json.load(f).get("from_release") or "")
    rel = os.path.join(prefix, "releases", name)
    if not name or "/" in name or not os.path.isdir(rel):
        write_update_result(data_dir, "not_reverted", "the version to go back to is no longer here")
        return "not_reverted"
    run(["systemctl", "stop", SERVICE], timeout=180)
    try:
        take_snapshot(data_dir, label="before-revert", extra={"kind": "revert"})
        restore_snapshot(snapshot, data_dir)
    except (OSError, ValueError) as e:
        run(["systemctl", "start", SERVICE], timeout=120)
        write_update_result(data_dir, "not_reverted", f"the earlier data could not be put back: {e}")
        return "not_reverted"
    point_at(rel, prefix)
    run(["systemctl", "reset-failed", SERVICE], timeout=30)
    run(["systemctl", "start", SERVICE], timeout=120)
    ok, why = healthy(port, stopped=lambda: restarts(run))
    write_update_result(data_dir, "reverted" if ok else "not_reverted", why)
    return "reverted" if ok else "not_reverted"


def start_back(snapshot_id: str, data_dir: str, port: int, prefix: str = PREFIX, run: Any = None) -> None:
    """Hands going back to a helper that outlives the restart. Raises UpdateFailed when it cannot."""
    from backend.services.data_snapshot import list_snapshots

    run = run or _run
    snap = next((s for s in list_snapshots(data_dir) if s["id"] == snapshot_id), None)
    if not snap:
        raise UpdateFailed("that earlier version is not available")
    current = os.path.realpath(os.path.join(prefix, "current"))
    code, said = run(
        [
            "systemd-run",
            "--unit",
            f"kiboto-revert-{int(time.time())}",
            "--collect",
            "--quiet",
            f"--working-directory={current}",
            f"--setenv=DATA_DIR={data_dir}",
            os.path.join(current, "venv", "bin", "python"),
            "-m",
            "backend.services.native_update",
            "back",
            snap["path"],
            data_dir,
            str(port),
        ],
        timeout=30,
    )
    if code != 0:
        raise UpdateFailed(f"going back could not be handed over: {said}")


def start(image: str, version: str, data_dir: str, port: int, prefix: str = PREFIX, run: Any = None) -> str:
    """Makes the new version ready, then hands the switch to a helper that outlives the restart.
    Returns the new version's folder. Raises UpdateFailed when it could not be made ready."""
    run = run or _run
    rel = prepare(image, version, prefix, run)
    python = os.path.join(os.path.realpath(os.path.join(prefix, "current")), "venv", "bin", "python")
    unit = f"kiboto-update-{int(time.time())}"
    code, said = run(
        [
            "systemd-run",
            "--unit",
            unit,
            "--collect",
            "--quiet",
            f"--working-directory={os.path.realpath(os.path.join(prefix, 'current'))}",
            f"--setenv=DATA_DIR={data_dir}",
            python,
            "-m",
            "backend.services.native_update",
            "apply",
            rel,
            data_dir,
            str(port),
            image,
        ],
        timeout=30,
    )
    if code != 0:
        shutil.rmtree(rel, ignore_errors=True)
        raise UpdateFailed(f"the update could not be handed over: {said}")
    return rel


def main(argv: list[str]) -> int:
    if len(argv) >= 5 and argv[1] == "apply":
        time.sleep(2.5)  # the answer to the person's click goes out first
        result = apply(argv[2], argv[3], int(argv[4]), argv[5] if len(argv) > 5 else "")
        print(result)
        return 0 if result == "updated" else 1
    if len(argv) == 5 and argv[1] == "back":
        time.sleep(2.5)
        result = back(argv[2], argv[3], int(argv[4]))
        print(result)
        return 0 if result == "reverted" else 1
    print("usage: python -m backend.services.native_update apply <release> <data dir> <port> [image]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
