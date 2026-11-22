"""The apps of a machine that was set up again come back.

A Kiboto app is a Compose project whose file is in the apps' folder on a pool (apps_place.py). The
containers are not part of the settings, so after the settings came back from the copy on the
pools (pool_copy.py) the files are there and the containers are not. At the first start after
such a restore every app folder with a Compose file and no container is applied again, in the
background once Docker answers. An app that asks for host-level access (its own network, a device,
privileged mode) is not started without a person's yes: it is named in the activity log instead,
to be started from its folder.

Apps are only looked for at that start, never on a timer: listing the apps' folder reads its pool."""

import os
import threading
import time
from collections.abc import Callable
from typing import Any

from backend.config import logger

COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yaml", "compose.yml")
WAIT_FOR_DOCKER = 180.0


def _compose_file(folder: str) -> str:
    for name in COMPOSE_NAMES:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return ""


def _projects_with_containers(request: Callable[..., tuple[int, Any]]) -> set[str]:
    code, rows = request("GET", "/containers/json?all=1")
    if code != 200 or not isinstance(rows, list):
        raise RuntimeError("Docker did not list its containers")
    return {str((r.get("Labels") or {}).get("com.docker.compose.project") or "") for r in rows} - {""}


def waiting(root: str, request: Callable[..., tuple[int, Any]]) -> list[str]:
    """The app folders under `root` that have a Compose file and no container, by name."""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    running = _projects_with_containers(request)
    return [n for n in names if not n.startswith(".") and n not in running and _compose_file(os.path.join(root, n))]


def start_one(name: str, root: str) -> str:
    """Applies one app's file. '' when it runs, 'needs_ok' when it asks for host-level access, else why not."""
    from backend.services import compose_apply, docker_stacks
    from backend.services.app_catalog import pull_image_blocking
    from backend.services.container_mutator import docker_request

    folder = os.path.join(root, name)
    with open(_compose_file(folder), encoding="utf-8") as f:
        compose = f.read()
    env = None
    if os.path.isfile(os.path.join(folder, ".env")):
        with open(os.path.join(folder, ".env"), encoding="utf-8") as f:
            env = f.read()
    try:
        inputs = docker_stacks._apply_inputs(name, compose, env)
        result = compose_apply.apply_built(
            inputs["built"],
            inputs["current"],
            compose_apply.Docker(docker_request, pull_image_blocking),
            False,
            elevated_reasons=docker_stacks.elevated_reasons_for,
        )
    except compose_apply.ComposeError as e:
        return "needs_ok" if "host-level access" in str(e) else str(e)
    return "" if result.get("ok") else str(result.get("error") or "it did not start")


def start_all(
    request: Callable[..., tuple[int, Any]] | None = None, sleep: Callable[[float], Any] = time.sleep
) -> dict[str, str]:
    """Waits for Docker, then starts every app that came back without a container. {name: '' or why not}."""
    from backend.services.app_catalog import default_storage_root
    from backend.state import add_event, event_text

    if request is None:
        from backend.services.container_mutator import docker_request as request
    waited = 0.0
    while True:
        try:
            todo = waiting(default_storage_root(), request)
            break
        except (OSError, RuntimeError):
            if waited >= WAIT_FOR_DOCKER:
                logger.warning("[Apps] Docker did not answer; the apps that came back were not started")
                return {}
            sleep(5.0)
            waited += 5.0
    root = default_storage_root()
    done: dict[str, str] = {}
    for name in todo:
        try:
            done[name] = start_one(name, root)
        except (OSError, RuntimeError, ValueError) as e:
            done[name] = str(e)
    started = [n for n, why in done.items() if not why]
    held = [n for n, why in done.items() if why == "needs_ok"]
    failed = {n: why for n, why in done.items() if why and why != "needs_ok"}
    if started:
        add_event("success", "Apps started again", ", ".join(started), event_text("apps_back", apps=", ".join(started)))
    if held:
        add_event(
            "warning",
            "Apps waiting for your OK",
            f"{', '.join(held)} ask for access to the machine itself, so they were not started. Start them under Apps.",
            event_text("apps_back_held", apps=", ".join(held)),
        )
    for name, why in failed.items():
        add_event(
            "warning", "An app did not start", f"{name}: {why}", event_text("apps_back_failed", app=name, error=why)
        )
    logger.info(
        "[Apps] After the restore: %s started, %s waiting for an OK, %s failed", len(started), len(held), len(failed)
    )
    return done


def start_soon() -> None:
    threading.Thread(target=start_all, name="apps-back", daemon=True).start()
