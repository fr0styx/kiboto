"""High availability: the first NAS's apps on the second one.

An app is not a setting. Its set-up lives in Docker on the first NAS and its files in a folder,
so the settings copy has neither. The first NAS therefore tells the second one, with every fetch
and over the sealed link, how each of its apps is set up: a Compose file rebuilt from the app's
containers, with the folders it uses. The second NAS keeps that sealed and does nothing with it.

After a takeover the Backup page lists those apps, and **Add here** on one sets it up on this
box, through the same safe apply as a restored app: everything is taken back if a part does not
come up. An app can be added when every folder it uses is inside a folder kept in step (it is
then pointed at this box's copy), or is a folder this box has under the same path. Its files are
last night's. An app that asks for host-level access is not added from here: that is for a person
to decide in Apps.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import yaml

from backend import secret_box
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json
from backend.services import ha_link
from backend.services.ha_link import LinkError

DIR = os.path.join(DATA_DIR, "ha")  # beside the settings copy (ha_state) and the folders' record
KEPT = "apps.json"
DONE = "apps_added.json"
MAX_APPS = 200
MAX_TEXT = 4 * 1024 * 1024  # all set-ups together, in one sealed answer

_lock = threading.Lock()
_adding: dict[str, dict[str, Any]] = {}


# --- on the first NAS: how its apps are set up ------------------------------------------------------
def setups() -> list[dict[str, Any]]:
    """Every app of this box that is not Kiboto itself: {name, compose, folders, images}. The
    Compose text is rebuilt from the containers, so every folder in it is a full path."""
    from backend.hardware.docker_stats import is_kiboto_own
    from backend.services.app_backup import compose_of
    from backend.services.container_mutator import docker_request
    from backend.services.docker_stacks import stack_of

    status, listed = docker_request("GET", "/containers/json?all=1")
    if status != 200 or not isinstance(listed, list):
        return []
    groups: dict[str, list[str]] = {}
    for c in listed:
        cid = str(c.get("Id") or "")
        name = str((c.get("Names") or [""])[0]).lstrip("/")
        if not cid or not name or is_kiboto_own(cid, name):
            continue
        groups.setdefault(stack_of(c.get("Labels") or {}) or name, []).append(cid)
    out: list[dict[str, Any]] = []
    size = 0
    for app in sorted(groups)[:MAX_APPS]:
        inspects = []
        for cid in groups[app]:
            st, info = docker_request("GET", f"/containers/{cid}/json")
            if st == 200 and isinstance(info, dict):
                inspects.append(info)
        compose = compose_of(inspects) if inspects else ""
        size += len(compose)
        if not compose or size > MAX_TEXT:
            continue
        folders = {
            str(m.get("Source"))
            for i in inspects
            for m in i.get("Mounts") or []
            if m.get("Type") == "bind" and str(m.get("Source") or "").startswith("/")
        }
        images = {str((i.get("Config") or {}).get("Image") or "") for i in inspects}
        out.append({"name": app, "compose": compose, "folders": sorted(folders), "images": sorted(images - {""})})
    return out


def _list(_args: dict[str, Any]) -> dict[str, Any]:
    if ha_link.role() != "first":
        raise LinkError("refused", "Only a first NAS tells how its apps are set up.")
    return {"apps": setups()}


# --- on the second NAS: keeping what the first one said ---------------------------------------------
def fetch(send: ha_link.Sender | None = None) -> int:
    """Asks the first NAS how its apps are set up and keeps the answer, sealed. How many apps.
    A first NAS from before this question refuses; then what is kept stays."""
    if ha_link.role() != "second":
        return 0
    said = ha_link.call("apps_list", send=send) if send else ha_link.call("apps_list")
    apps = [
        {
            "name": str(a.get("name") or "")[:64],
            "compose": str(a.get("compose") or ""),
            "folders": [str(f) for f in a.get("folders") or [] if str(f).startswith("/")][:64],
            "images": [str(i)[:200] for i in a.get("images") or []][:16],
        }
        for a in (said or {}).get("apps") or []
        if isinstance(a, dict) and a.get("name") and a.get("compose")
    ][:MAX_APPS]
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    atomic_write_json(
        os.path.join(DIR, KEPT),
        {"at": time.time(), "count": len(apps), "apps": secret_box.seal(json.dumps(apps))},
    )
    return len(apps)


def kept() -> list[dict[str, Any]]:
    data = read_json(os.path.join(DIR, KEPT), {})
    if not isinstance(data, dict) or not data.get("apps"):
        return []
    try:
        apps = json.loads(secret_box.unseal(str(data["apps"])))
    except ValueError:  # the key changed and this was not sealed again, or the file is damaged
        logger.warning("[HA] the kept set-ups of the first NAS's apps could not be opened")
        return []
    return [a for a in apps if isinstance(a, dict)] if isinstance(apps, list) else []


def kept_at() -> float | None:
    data = read_json(os.path.join(DIR, KEPT), {})
    return float(data["at"]) if isinstance(data, dict) and data.get("at") else None


@json_locked(lambda *a, **k: os.path.join(DIR, KEPT))
def reseal() -> int:
    """After the install's secret key was replaced: the kept set-ups sealed with the new one."""
    path = os.path.join(DIR, KEPT)
    data = read_json(path, {})
    if not isinstance(data, dict) or not secret_box.is_sealed(str(data.get("apps") or "")):
        return 0
    data["apps"] = secret_box.seal(secret_box.unseal(data["apps"]))
    atomic_write_json(path, data)
    return 1


def forget() -> None:
    """Unpaired: the set-ups go. Apps that were added here are this box's own and stay."""
    for name in (KEPT, DONE):
        try:
            os.remove(os.path.join(DIR, name))
        except FileNotFoundError:
            continue
        except OSError:
            logger.warning("[HA] %s could not be removed", name, exc_info=True)
    _adding.clear()


# --- pointing an app at this box's folders -----------------------------------------------------------
def placed(app: dict[str, Any], places: dict[str, Any], kept_names: list[str]) -> tuple[dict[str, str], dict[str, Any]]:
    """Where each folder of the app is on this box ({their path: path here}), and why the app
    cannot be added ({} when it can): {"why": "folder_not_kept", "folder": name} for a folder in a
    shared folder of the first NAS that is not kept here, {"why": "folder_missing", "path": p} for
    one outside its shared folders that this box does not have."""
    shares, first_paths = places["shares"], places["first_paths"]
    where: dict[str, str] = {}
    for folder in app.get("folders") or []:
        inside = [
            (name, path)
            for name, path in first_paths.items()
            if folder == path or folder.startswith(path.rstrip("/") + "/")
        ]
        if inside:
            name, path = max(inside, key=lambda found: len(found[1]))
            if name not in kept_names or name not in shares:
                return {}, {"why": "folder_not_kept", "folder": name}
            where[folder] = shares[name].rstrip("/") + folder[len(path.rstrip("/")) :]
        elif os.path.exists(folder):
            where[folder] = folder
        else:
            return {}, {"why": "folder_missing", "path": folder}
    return where, {}


def repointed(compose: str, where: dict[str, str]) -> str:
    """The Compose text with every folder replaced by where it is on this box."""
    doc = yaml.safe_load(compose)
    for service in (doc.get("services") or {}).values() if isinstance(doc, dict) else []:
        volumes = service.get("volumes") if isinstance(service, dict) else None
        if not isinstance(volumes, list):
            continue
        for at, item in enumerate(volumes):
            if isinstance(item, dict) and str(item.get("source") or "") in where:
                item["source"] = where[str(item["source"])]
            elif isinstance(item, str) and item.split(":")[0] in where:
                src, _, rest = item.partition(":")
                volumes[at] = f"{where[src]}:{rest}"
    return yaml.safe_dump(doc, sort_keys=False)


def _here_already() -> set[str]:
    """The names apps and containers on this box have."""
    from backend.services.container_mutator import docker_request
    from backend.services.docker_stacks import stack_of

    status, listed = docker_request("GET", "/containers/json?all=1")
    names: set[str] = set()
    for c in listed if status == 200 and isinstance(listed, list) else []:
        names.add(str((c.get("Names") or [""])[0]).lstrip("/"))
        names.add(stack_of(c.get("Labels") or {}))
    return names - {""}


def _done() -> dict[str, Any]:
    data = read_json(os.path.join(DIR, DONE), {})
    return data if isinstance(data, dict) else {}


@json_locked(lambda *a, **k: os.path.join(DIR, DONE))
def _note(name: str, result: dict[str, Any]) -> None:
    data = _done()
    data[name] = result
    atomic_write_json(os.path.join(DIR, DONE), data)


def listing() -> list[dict[str, Any]]:
    """The first NAS's apps as the screen lists them after a takeover: each with whether it can be
    added here and why not, and how adding it went. Never the set-up itself."""
    from backend.services import ha_bring, ha_folders

    apps = kept()
    if not apps:
        return []
    places, names, here, done = ha_bring.here(), ha_folders.chosen(), _here_already(), _done()
    out = []
    for app in apps:
        name = str(app.get("name") or "")
        _where, why = placed(app, places, names)
        state = dict(_adding.get(name) or done.get(name) or {})
        if name in here and state.get("state") != "adding":
            state = {**state, "state": "here"}
        out.append(
            {"name": name, "images": app.get("images") or [], "why": why or None, **{"state": "", "error": ""}, **state}
        )
    return out


def _add(name: str, compose: str, actor: str) -> None:
    from backend.services import compose_apply
    from backend.services.app_catalog import pull_image_blocking
    from backend.services.container_mutator import docker_request
    from backend.services.docker_stacks import elevated_reasons_for

    result: dict[str, Any] = {"state": "failed", "error": "", "at": time.time()}
    try:
        built = compose_apply.build(compose, None, name, "/")
        if compose_apply.plan(built, [], elevated_reasons_for)["elevated"]:
            result["state"] = "needs_review"
        else:
            res = compose_apply.apply_built(
                built,
                [],
                compose_apply.Docker(docker_request, pull_image_blocking),
                False,
                elevated_reasons=elevated_reasons_for,
            )
            result.update(state="added" if res.get("ok") else "failed", error=str(res.get("error") or "")[:300])
    except (compose_apply.ComposeError, OSError, ValueError, KeyError, TypeError, RuntimeError) as e:
        result["error"] = str(e)[:300]
    finally:
        _note(name, result)
        _adding.pop(name, None)
        ha_link.audit("app_added", f"{name}: {result['state']}", actor)
        logger.info("[HA] the app %s of the first NAS: %s %s", name, result["state"], result["error"])


def add(name: str, actor: str = "") -> dict[str, Any]:
    """Sets one of the first NAS's apps up on this box, in the background. Only after a takeover.
    Raises LinkError: not after a takeover, no such app, here already, or its folders are not here."""
    from backend.services import ha_bring, ha_folders

    if ha_link.role() != "took_over":
        raise LinkError("not_taken_over", "Apps of the first NAS are added after this NAS has taken over.")
    app = next((a for a in kept() if a.get("name") == name), None)
    if app is None:
        raise LinkError("no_app", f"The first NAS has no app named {name}.")
    where, why = placed(app, ha_bring.here(), ha_folders.chosen())
    if why:
        raise LinkError("app_folders", "A folder this app uses is not on this NAS.")
    with _lock:
        if name in _adding or name in _here_already():
            raise LinkError("app_here", f"An app named {name} is on this NAS already.")
        _adding[name] = {"state": "adding", "error": "", "at": time.time()}
    compose = repointed(str(app.get("compose") or ""), where)
    threading.Thread(target=_add, args=(name, compose, actor), name="ha-app-add", daemon=True).start()
    return {"state": "adding"}


def view() -> dict[str, Any]:
    """What the screen adds to the link's status: how many apps the first NAS told about, and when."""
    data = read_json(os.path.join(DIR, KEPT), {})
    count = int(data.get("count") or 0) if isinstance(data, dict) else 0
    return {"apps_known": count, "apps_at": kept_at()}


ha_link.HANDLERS.update(apps_list=_list)
ha_link.ON_UNPAIR.append(forget)
