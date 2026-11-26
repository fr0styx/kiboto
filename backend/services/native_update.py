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


class Damaged(UpdateFailed):
    """The download is there but its files are empty: a power cut while Docker saved it."""


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


SITE = "site-packages"  # in a release folder: the image's Python packages, until they go into place


def _site_from_image(cid: str, site: str, dest: str, prefix: str, run: Any) -> bool:
    """The image's own Python packages, copied out when they are for this machine's Python and no
    version has an environment for these requirements yet. False when pip has to make it."""
    here = f"/python{sys.version_info[0]}.{sys.version_info[1]}/site-packages"
    lock = os.path.join(dest, "requirements.lock")
    if not site.startswith("/opt/kiboto/") or not site.endswith(here) or ".." in site or not os.path.isfile(lock):
        return False
    if os.path.exists(os.path.join(prefix, "venvs", lock_key(lock), ".ready")):
        return False  # another version already has it
    code, said = run(["docker", "cp", f"{cid}:{site}", os.path.join(dest, SITE)], timeout=900)
    if code != 0:
        logger.warning("[Update] The image's Python packages could not be copied (%s); pip makes them", said)
        shutil.rmtree(os.path.join(dest, SITE), ignore_errors=True)
        return False
    return True


def extract(image: str, dest: str, prefix: str = PREFIX, run: Any = None) -> dict[str, str]:
    """Copies Kiboto's own files out of the image into `dest`, and its Python packages when this
    machine can use them. Returns the image's build values. Nothing of the image runs: a container
    is made from it, read and removed."""
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
        values = dict(str(e).split("=", 1) for e in env if "=" in str(e))
        build = {k: v for k, v in values.items() if k in BUILD_ENV}
        _site_from_image(cid, values.get("KIBOTO_SITE", ""), dest, prefix, run or _run)
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
        from_image = os.path.join(rel, SITE)
        if code == 0 and os.path.isdir(from_image):  # the image's own packages: nothing downloaded
            site = os.path.join(venv, "lib", f"python{sys.version_info[0]}.{sys.version_info[1]}", SITE)
            shutil.rmtree(site, ignore_errors=True)
            os.makedirs(os.path.dirname(site), exist_ok=True)
            shutil.move(from_image, site)
        elif code == 0:
            pip = [os.path.join(venv, "bin", "python"), "-m", "pip", "-q", "install", "--no-compile"]
            code, said = run([*pip, "--require-hashes", "-r", lock], timeout=1200)
        if code != 0:
            shutil.rmtree(venv, ignore_errors=True)
            raise UpdateFailed(f"its Python packages could not be installed: {said}")
        with open(ready, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S\n"))
    shutil.rmtree(os.path.join(rel, SITE), ignore_errors=True)  # not needed: the environment was there
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


APT_PIN = "/etc/apt/preferences.d/kiboto-debian13.pref"


def _same_text(path: str, text: str) -> bool:
    if not os.path.isfile(path):
        return False
    with open(path, encoding="utf-8") as f:
        return f.read() == text


def keep_debian(rel: str, path: str | None = None) -> str:
    """Keeps this machine on Debian 13: apt installs no package of another Debian release while the
    release's packaging/kiboto-debian13.pref is in apt's preferences, since Kiboto's Python
    environment, the root service and the updater would stop together on Debian 14's Python.
    KIBOTO_KEEP_DEBIAN=0 takes the file away. Returns "written", "kept", "removed" or "" (no apt
    here, or a version without the file)."""
    from backend.config import SETTINGS

    path = path or APT_PIN
    if not os.path.isdir(os.path.dirname(path)):
        return ""
    if not getattr(SETTINGS, "keep_debian", True):
        if os.path.exists(path):
            os.remove(path)
            logger.warning("[Update] KIBOTO_KEEP_DEBIAN=0: apt may now move this machine to another Debian release")
            return "removed"
        return ""
    try:
        with open(os.path.join(rel, "packaging", "kiboto-debian13.pref"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    if _same_text(path, text):
        return "kept"
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    logger.info("[Update] This machine stays on Debian 13 (%s)", path)
    return "written"


def ensure_units(rel: str, run: Any = None, unit_dir: str | None = None, door_current: Any = None) -> list[str]:
    """The service files of the running version where an update made by an older one left older
    ones, or none (the host door's came after install.sh had run). The door is (re)started at each
    start of Kiboto, so it runs the same version; Kiboto's own service takes a new file at its
    next start. Returns the files that changed."""
    unit_dir = unit_dir or UNIT_DIR  # read now, not when the module was loaded
    run = run or _run
    changed = []
    for name in UNITS:
        src = os.path.join(rel, "packaging", name)
        try:
            with open(src, encoding="utf-8") as f:
                want = f.read()
        except OSError:
            continue
        if not want.strip():  # an empty unit file is a masked service to systemd: never put one in place
            logger.warning("[Update] %s of %s is empty: the one in place stays", name, os.path.basename(rel))
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
    # the door again only when it runs other code: a restart also ends what it started (the
    # encrypted folders and cloud folders it opened)
    stale = "kiboto-door.service" in changed or door_current is None or not door_current()
    if os.path.exists(os.path.join(unit_dir, "kiboto-door.service")) and stale:
        run(["systemctl", "restart", "kiboto-door.service"], timeout=60)
    return changed


# The lowest version this machine installs (security review finding 9): an older release, signed
# as it is, may have a known bug in the root service, and a taken-over web process could ask for it.
# Raised by a release that fixes the root service (docs/RELEASING.md); never above __version__.
# Going back to a version kept on the machine (Revert) is not an install and is not limited.
LOWEST_VERSION = "2.0.8"
_VERSION_LINE = re.compile(r'^__version__ = "([0-9]+)\.([0-9]+)\.([0-9]+)[^"]*"$', re.M)


def version_of(rel: str) -> tuple[int, int, int] | None:
    """The version an unpacked image says it is, from its own code, not from what was asked for."""
    try:
        with open(os.path.join(rel, "backend", "__init__.py"), encoding="utf-8") as f:
            m = _VERSION_LINE.search(f.read())
    except OSError:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _not_too_old(rel: str) -> None:
    found = version_of(rel)
    lowest = tuple(int(x) for x in LOWEST_VERSION.split("."))
    if found is None:
        raise UpdateFailed("the image does not say which version it is, so it is not installed")
    if found < lowest:
        shown = ".".join(str(x) for x in found)
        raise UpdateFailed(f"this machine installs Kiboto {LOWEST_VERSION} or newer, and the image is {shown}")


def prepare(image: str, version: str, prefix: str = PREFIX, run: Any = None) -> str:
    """Makes the new version ready beside the running one. Returns its folder."""
    run = run or _run
    rel = os.path.join(prefix, "releases", f"{version or 'new'}-{time.strftime('%Y%m%d%H%M%S')}")
    try:
        extract(image, rel)
        _whole(rel)
        _not_too_old(rel)  # before its Python packages are installed or any of its code runs
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
        if isinstance(e, Damaged):
            _forget(image)
        raise UpdateFailed(str(e)) from e
    return rel


def _whole(rel: str) -> None:
    """A download cut short (the machine lost power while Docker saved the image) can leave all of
    the image's files in place but empty, and Docker serves them as they are. Such a version is
    refused before anything is switched: its service files would read as masked services."""
    try:
        with open(os.path.join(rel, "backend", "__init__.py"), encoding="utf-8") as f:
            named = "__version__" in f.read()
    except OSError:
        named = False
    units = [os.path.join(rel, "packaging", name) for name in UNITS]
    if not named or any(os.path.isfile(u) and os.path.getsize(u) == 0 for u in units):
        raise Damaged("the downloaded version is damaged (its files are empty); it is downloaded again next time")


def _image_repo(ref: str) -> str:
    """ghcr.io/fr0styx/kiboto from ghcr.io/fr0styx/kiboto:2.0.7 or ...@sha256:..."""
    repo = ref.split("@", 1)[0]
    head, _, tail = repo.rpartition("/")
    return f"{head}/{tail.split(':', 1)[0]}" if head else tail.split(":", 1)[0]


def forget_images() -> list[str]:
    """After an update held: Kiboto's images left in Docker go (about 1.9 GB each). A machine Kiboto
    runs uses the files copied out of them, and going back uses the versions kept on disk, never an
    image. One a container still uses is left (Docker refuses). Returns the image ids removed."""
    from backend.services.image_signature import IMAGE_REPOS

    try:
        status, images = docker_client.request("GET", "/images/json")
    except docker_client.DockerError as e:
        logger.warning("[Update] Kiboto's old images could not be listed: %s", e)
        return []
    gone = []
    for img in images if status == 200 and isinstance(images, list) else []:
        refs = [*(img.get("RepoTags") or []), *(img.get("RepoDigests") or [])]
        if not any(_image_repo(str(r)) in IMAGE_REPOS for r in refs):
            continue
        image_id = str(img.get("Id") or "")
        try:
            st, said = docker_client.request("DELETE", f"/images/{image_id}?noprune=false")
        except docker_client.DockerError as e:
            st, said = 0, str(e)
        if st == 200:
            gone.append(image_id)
        else:
            logger.info("[Update] Kiboto's image %s stays: %s", image_id[:19], said)
    if gone:
        logger.info("[Update] Removed %d of Kiboto's images no version needs", len(gone))
    return gone


def _forget(image: str) -> None:
    """The damaged image goes, so the next try downloads it again instead of reading the same."""
    try:
        status, said = docker_client.request("DELETE", f"/images/{image}")
    except docker_client.DockerError as e:
        status, said = 0, str(e)
    if status not in (200, 404):
        logger.warning("[Update] the damaged download %s stays: %s", image, said)


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


ROOTS_LOGS = ("door-audit.log", "docker-proxy-audit.log")  # written by root: they stay root's


def _start_and_check(port: int, run: Any) -> tuple[bool, str]:
    """Starts the service and waits for it to hold; a start systemd refuses (a masked or broken
    unit) is an answer at once, not after the whole wait."""
    code, said = run(["systemctl", "start", SERVICE], timeout=120)
    if code != 0:
        return False, f"the new version could not be started: {said.strip()[-200:] or code}"
    return healthy(port, stopped=lambda: restarts(run))


def _record(data_dir: str, result: str, why: str = "", **extra: Any) -> None:
    """How the update ended, for Kiboto to say after its start; written by the helper (root), so
    the file goes to the data folder's owner, who must read it and mark it reported."""
    from backend.services import self_updater

    self_updater.write_update_result(data_dir, result, why, **extra)
    path = os.path.join(data_dir, self_updater.RESULT_FILE)
    try:
        st = os.stat(data_dir)
        if st.st_uid != 0 and os.path.exists(path):
            os.lchown(path, st.st_uid, st.st_gid)
    except OSError as e:
        logger.warning("[Update] %s stays root's: %s", self_updater.RESULT_FILE, e)


def _hand_back(data_dir: str) -> None:
    """What the helper (root) made or put back in the data folder (snapshots, restored files)
    goes to the folder's owner before Kiboto starts: the user kiboto when Kiboto is not root
    (ADR 0006), which could not open them otherwise. Nothing changes where the folder is root's."""
    try:
        st = os.stat(data_dir)
    except OSError:
        return
    if st.st_uid == 0:
        return
    for folder, dirs, files in os.walk(data_dir):
        for name in [*dirs, *files]:
            if folder == data_dir and name in ROOTS_LOGS:
                continue
            try:
                os.lchown(os.path.join(folder, name), st.st_uid, st.st_gid)
            except OSError as e:
                logger.warning("[Update] %s stays root's: %s", name, e)


WEB_USER_DROP_IN = "/etc/systemd/system/kiboto.service.d/web-user.conf"  # services/web_user.DROP_IN


def _in_the_owners_name(data_dir: str, what: list[str]) -> str:
    """Takes or puts back a snapshot (data_snapshot's `take` or `restore`). Where this is root and the
    data folder is someone else's (the web user's, ADR 0006), it is done as that user in a process of
    its own: root following that folder's links and file lists could be made to write anywhere.
    Returns what was printed (a new snapshot's folder); an OSError says why it failed."""
    from backend.services import data_snapshot

    st = os.stat(data_dir)
    if os.geteuid() != 0 or st.st_uid == 0:
        if what[0] == "take":
            return data_snapshot.take_snapshot(what[1], label=what[2], extra=json.loads(what[3]))
        data_snapshot.restore_snapshot(what[1], what[2])
        return ""
    _hand_back(data_dir)  # what root left there earlier is the owner's to replace
    code_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    res = subprocess.run(
        [sys.executable, "-m", "backend.services.data_snapshot", *what],
        user=st.st_uid,
        group=st.st_gid,
        extra_groups=[],
        cwd=code_root,
        env={**os.environ, "DATA_DIR": data_dir, "HOME": data_dir},
        capture_output=True,
        text=True,
        timeout=3600,
        check=False,
    )
    if res.returncode != 0:
        raise OSError((res.stderr or res.stdout or "it did not finish").strip()[-400:])
    return (res.stdout.strip().splitlines() or [""])[-1]


def _root_for_older(rel: str, run: Any, drop_in: str = WEB_USER_DROP_IN) -> None:
    """A version from before ADR 0006 step 9 cannot run as the user kiboto (it does root's work
    itself): going back to one, Kiboto runs as root again."""
    if os.path.exists(drop_in) and not os.path.exists(os.path.join(rel, "backend", "services", "web_user.py")):
        os.remove(drop_in)
        run(["systemctl", "daemon-reload"], timeout=60)
        logger.warning("[Update] %s runs as root: it is older than Kiboto without root", os.path.basename(rel))


def _door_follows(rel: str, run: Any) -> None:
    """The helper (root) puts this version's service files in place and starts the host door again
    on its code before Kiboto starts: once Kiboto is not root (ADR 0006) it cannot do that itself."""
    _root_for_older(rel, run)
    try:
        ensure_units(rel, run)  # no door_current: the door is started again whatever it runs
    except OSError as e:
        logger.warning("[Update] the service files of %s were not put in place: %s", os.path.basename(rel), e)


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
    prune_venvs(prefix)


def prune_venvs(prefix: str = PREFIX) -> list[str]:
    """Removes the Python environments no kept version uses (about 460 MB each). One that is not
    finished (no .ready in it) is left: it may be being made for a version right now."""
    root, venvs = os.path.join(prefix, "releases"), os.path.join(prefix, "venvs")
    try:
        names = os.listdir(venvs)
    except OSError:
        return []
    used = set()
    for rel in os.listdir(root) if os.path.isdir(root) else []:
        link = os.path.join(root, rel, "venv")
        if os.path.islink(link):
            used.add(os.path.realpath(link))
    gone = []
    for name in names:
        venv = os.path.join(venvs, name)
        if os.path.realpath(venv) in used or not os.path.exists(os.path.join(venv, ".ready")):
            continue
        shutil.rmtree(venv, ignore_errors=True)
        gone.append(name)
    if gone:
        logger.info("[Update] Removed %d Python environment(s) no kept version uses", len(gone))
    return gone


def apply(rel: str, data_dir: str, port: int, image: str = "", prefix: str = PREFIX, run: Any = None) -> str:
    """The helper's work, run outside the service: switch to `rel`, and back if it does not hold.
    Returns "updated", "rolled_back" or "not_applied"."""
    run = run or _run
    run(["systemctl", "stop", SERVICE], timeout=180)
    running = os.path.realpath(os.path.join(prefix, "current"))
    try:
        # the version this data belongs to: going back takes both together
        extra = {"kind": "update", "to": os.path.basename(rel), "from_release": os.path.basename(running)}
        snapshot = _in_the_owners_name(data_dir, ["take", data_dir, "before-update", json.dumps(extra)])
    except OSError as e:
        _hand_back(data_dir)
        run(["systemctl", "start", SERVICE], timeout=120)
        _record(data_dir, "not_applied", f"could not snapshot the data folder: {e}", to_image=image)
        return "not_applied"
    earlier = _previous(prefix)
    before = point_at(rel, prefix)
    _door_follows(rel, run)
    _hand_back(data_dir)
    ok, why = _start_and_check(port, run)
    if ok:
        _record(data_dir, "updated", why, to_image=image)
        prune(prefix)
        forget_images()
        return "updated"
    logger.error("[Update] The new version did not hold (%s): going back", why)
    run(["systemctl", "stop", SERVICE], timeout=180)
    try:
        _in_the_owners_name(data_dir, ["restore", snapshot, data_dir])
    except (OSError, ValueError) as e:
        why = f"{why}; the earlier data could not be put back: {e}"
    if before:
        point_at(before, prefix)
        _door_follows(before, run)
        _set_previous(prefix, earlier)  # the version that failed is nobody's "previous"
        shutil.rmtree(rel, ignore_errors=True)
    run(["systemctl", "reset-failed", SERVICE], timeout=30)  # a crash loop may have used up its starts
    _hand_back(data_dir)
    run(["systemctl", "start", SERVICE], timeout=120)
    _record(data_dir, "rolled_back", why, to_image=image)
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
    run = run or _run
    with open(os.path.join(snapshot, "manifest.json"), encoding="utf-8") as f:
        name = str(json.load(f).get("from_release") or "")
    rel = os.path.join(prefix, "releases", name)
    if not name or "/" in name or not os.path.isdir(rel):
        _record(data_dir, "not_reverted", "the version to go back to is no longer here")
        return "not_reverted"
    run(["systemctl", "stop", SERVICE], timeout=180)
    try:
        _in_the_owners_name(data_dir, ["take", data_dir, "before-revert", json.dumps({"kind": "revert"})])
        _in_the_owners_name(data_dir, ["restore", snapshot, data_dir])
    except (OSError, ValueError) as e:
        _hand_back(data_dir)
        run(["systemctl", "start", SERVICE], timeout=120)
        _record(data_dir, "not_reverted", f"the earlier data could not be put back: {e}")
        return "not_reverted"
    point_at(rel, prefix)
    _door_follows(rel, run)
    run(["systemctl", "reset-failed", SERVICE], timeout=30)
    _hand_back(data_dir)
    ok, why = _start_and_check(port, run)
    _record(data_dir, "reverted" if ok else "not_reverted", why)
    return "reverted" if ok else "not_reverted"


def _door(op: str, here: Any, **args: Any) -> Any:
    """`op` in the host door where it runs (ADR 0006), else `here`; a failure is UpdateFailed."""
    from backend import door

    try:
        return door.via(op, here, **args)
    except UpdateFailed:
        raise
    except (RuntimeError, ValueError) as e:  # the door's refusal or failure, said as it was
        raise UpdateFailed(str(e)) from None


def add_missing_tools_now() -> list[str]:
    """What the running version needs from Debian (add_missing_tools), at start; through the door
    where it runs."""
    return _door("packages.add_missing", lambda: add_missing_tools(os.path.join(PREFIX, "current")))


def start_back(snapshot_id: str, data_dir: str, port: int, prefix: str = PREFIX, run: Any = None) -> None:
    """Hands going back to a helper that outlives the restart. Raises UpdateFailed when it cannot.
    Through the host door where it runs (ADR 0006), with the door's own data folder and port."""
    if run is None and prefix == PREFIX:
        _door("update.back", lambda snapshot_id: _start_back_here(snapshot_id, data_dir, port), snapshot_id=snapshot_id)
        return
    _start_back_here(snapshot_id, data_dir, port, prefix, run)


def _start_back_here(snapshot_id: str, data_dir: str, port: int, prefix: str = PREFIX, run: Any = None) -> None:
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
    Returns the new version's folder. Raises UpdateFailed when it could not be made ready.
    Through the host door where it runs (ADR 0006): the door checks the image's signature itself
    (image_signature.install_allowed) and uses its own data folder and port."""
    if run is None and prefix == PREFIX:
        return _door(
            "update.start",
            lambda image, version: _start_here(image, version, data_dir, port),
            image=image,
            version=version,
        )
    return _start_here(image, version, data_dir, port, prefix, run)


def _start_here(image: str, version: str, data_dir: str, port: int, prefix: str = PREFIX, run: Any = None) -> str:
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
