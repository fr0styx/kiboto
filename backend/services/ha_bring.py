"""High availability: what else a takeover brings along when the person asks for it. So far: the
first NAS's backups.

A takeover always brings the people (ha_takeover.py). Backups are a choice, because they act on
their own once they run: a copy job that mirrors would make its destination look like this box's
folder. So what comes along arrives switched off, and the person turns each one on after a look.

What can come along is what makes sense on this box: a copy job whose folder is one of the folders
kept in step here, and an off-site backup of such folders. A backup onto a drive of the first NAS
stays behind, as does a job for a folder this box does not keep. Passwords sealed with the first
NAS's key are sealed again with this box's own. The cloud sign-ins (rclone remotes) a job needs
come with it; one that would replace a different sign-in of the same name here does not.
"""

from __future__ import annotations

import configparser
import io
import json
import os
from typing import Any

from backend import secret_box
from backend.config import logger
from backend.fsutil import atomic_write_json, atomic_write_text, read_json

JOBS = "backup_jobs.json"
REPOS = "offsite_repos.json"
REMOTES = os.path.join("rclone", "rclone.conf")
KEYS = "offsite_keys"
CHOICES = ("backups",)


def _text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


def read_backups(folder: str) -> dict[str, Any]:
    """A box's backups as its data folder holds them: copy jobs, off-site backups with their keys,
    and the cloud sign-ins."""
    jobs = read_json(os.path.join(folder, JOBS), [])
    repos = read_json(os.path.join(folder, REPOS), {})
    repos = repos.get("repos") if isinstance(repos, dict) else {}
    keys: dict[str, str] = {}
    try:
        names = os.listdir(os.path.join(folder, KEYS))
    except OSError:
        names = []
    for name in names:
        if name.endswith(".key"):
            keys[name[: -len(".key")]] = _text(os.path.join(folder, KEYS, name)).strip()
    return {
        "jobs": [j for j in jobs if isinstance(j, dict)] if isinstance(jobs, list) else [],
        "repos": {str(k): v for k, v in repos.items() if isinstance(v, dict)} if isinstance(repos, dict) else {},
        "remotes": _text(os.path.join(folder, REMOTES)),
        "keys": keys,
    }


def here() -> dict[str, Any]:
    """This box's shared folders and pools, and where the first NAS has the folders kept in step."""
    from backend.hardware.pal_storage import get_storage_platform
    from backend.services import ha_folders

    try:
        pools = [(str(p.mountpoint).rstrip("/"), p.id) for p in get_storage_platform().list_pools() if p.mountpoint]
    except (OSError, RuntimeError, ValueError):
        logger.debug("[HA] the pools could not be read", exc_info=True)
        pools = []
    return {"shares": ha_folders.shares(), "pools": pools, "first_paths": ha_folders.first_paths()}


def _pool_of(path: str, pools: list[tuple[str, str]]) -> str:
    """The pool a folder is on: the one mounted nearest above it."""
    best = ("", "")
    for mount, pool_id in pools:
        if path and (path == mount or path.startswith(mount + "/")) and len(mount) >= len(best[0]):
            best = (mount, pool_id)
    return best[1]


def _parse(text: str) -> configparser.RawConfigParser:
    conf = configparser.RawConfigParser()
    conf.optionxform = str  # type: ignore[assignment,method-assign]  # keys as rclone wrote them
    try:
        conf.read_string(text or "")
    except configparser.Error:
        logger.warning("[HA] a file of cloud sign-ins could not be read; its sign-ins do not come along")
        return configparser.RawConfigParser()
    return conf


def _mapped(path: str, kept: list[tuple[str, str]]) -> str:
    """A path on the first NAS as the path of the same thing here, or nothing when it is not in a kept folder."""
    for theirs, ours in kept:
        if path == theirs or path.startswith(theirs.rstrip("/") + "/"):
            return ours.rstrip("/") + path[len(theirs.rstrip("/")) :]
    return ""


def _resealed(value: Any, their_key: str) -> str:
    return secret_box.seal(secret_box.unseal_with(str(value or ""), their_key)) if value else ""


def plan_backups(
    theirs: dict[str, Any], own: dict[str, Any], their_key: str, folders: list[str], places: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, int]]:
    """Which of the first NAS's backups come along, as this box's files would then read, and the
    count: {jobs, jobs_left, offsite, offsite_left}. Nothing is written here."""
    shares, pools, first_paths = places["shares"], places["pools"], places["first_paths"]
    names = [n for n in folders if n in shares]
    kept = [(first_paths[n], shares[n]) for n in names if first_paths.get(n)]
    mine, others = _parse(own["remotes"]), _parse(theirs["remotes"])
    added: list[str] = []

    def sign_in(name: str) -> bool:
        """The cloud sign-in is here already, or comes along (with the one it builds on)."""
        if not name or not others.has_section(name):
            return False
        wanted = dict(others.items(name))
        if mine.has_section(name):
            return dict(mine.items(name)) == wanted  # another sign-in of that name here: not replaced
        under = str(wanted.get("remote") or "").split(":")[0]
        if under and under != name and others.has_section(under) and not sign_in(under):
            return False
        mine.add_section(name)
        for key, value in wanted.items():
            mine.set(name, key, value)
        added.append(name)
        return True

    said = {"jobs": 0, "jobs_left": 0, "offsite": 0, "offsite_left": 0}
    jobs = list(own["jobs"])
    have = {str(j.get("id")) for j in jobs}
    for job in theirs["jobs"]:
        if job.get("kind") == "config" or str(job.get("id")) in have:
            continue  # a backup of the first NAS's own settings is its own; a job that is here is here
        share = str(job.get("source_subvolume") or "").split("/")[0]
        pool = _pool_of(shares[share], pools) if share in names else ""
        try:
            if not pool or (
                job.get("destination_type", "remote") == "remote" and not sign_in(str(job.get("remote_name") or ""))
            ):
                raise ValueError("not for this box")
            password = _resealed(job.get("encryption_password"), their_key)
        except ValueError:  # SecretBoxError is one: a password that cannot be opened
            said["jobs_left"] += 1
            continue
        jobs.append(
            {
                **job,
                "source_pool": pool,
                "enabled": False,
                "encryption_password": password,
                "last_run_at": None,
                "last_status": "idle",
                "last_error": None,
            }
        )
        said["jobs"] += 1

    repos = dict(own["repos"])
    keys: dict[str, str] = {}
    for repo_id, repo in theirs["repos"].items():
        if repo_id in repos:
            continue
        location = str(repo.get("location") or "")
        paths = [p for p in (_mapped(str(x), kept) for x in repo.get("paths") or []) if p]
        key = theirs["keys"].get(repo_id) or ""
        try:
            # a backup onto a drive of the first NAS stays with it; so does one of folders not kept here
            if location.startswith("/") or not paths or not key:
                raise ValueError("not for this box")
            if location.startswith("rclone:") and not sign_in(location.split(":")[1]):
                raise ValueError("its cloud sign-in is not here")
            rest = _resealed(repo.get("rest_password"), their_key)
        except ValueError:
            said["offsite_left"] += 1
            continue
        repos[repo_id] = {
            **repo,
            "paths": paths,
            "hour": None,  # no schedule: the person sets the hour after a look
            "last_backup": None,
            "last_check": None,
            "last_result": "",
            "last_drill": None,
            "last_drill_result": "",
            "replaces_job": "",
            "lock_check": None,
            **({"rest_password": rest} if "rest_password" in repo else {}),
        }
        keys[repo_id] = key
        said["offsite"] += 1

    out = io.StringIO()
    mine.write(out)
    return {"jobs": jobs, "repos": repos, "keys": keys, "remotes": out.getvalue() if added else ""}, said


def write_backups(staged: str, plan: dict[str, Any], said: dict[str, int]) -> list[str]:
    """Puts what comes along into the staged folder; the files the next start has to put in place."""
    wrote: list[str] = []
    if said["jobs"]:
        atomic_write_json(os.path.join(staged, JOBS), plan["jobs"])
        wrote.append(JOBS)
    if said["offsite"]:
        atomic_write_json(os.path.join(staged, REPOS), {"repos": plan["repos"]})
        wrote.append(REPOS)
        os.makedirs(os.path.join(staged, KEYS), mode=0o700, exist_ok=True)
        for repo_id, key in plan["keys"].items():
            rel = os.path.join(KEYS, f"{repo_id}.key")
            atomic_write_text(os.path.join(staged, rel), key, mode=0o600)
            wrote.append(rel)
    if plan["remotes"]:
        os.makedirs(os.path.join(staged, os.path.dirname(REMOTES)), mode=0o700, exist_ok=True)
        atomic_write_text(os.path.join(staged, REMOTES), plan["remotes"], mode=0o600)
        wrote.append(REMOTES)
    return wrote


def counts(names: set[str], read: Any) -> dict[str, int]:
    """How many backups a settings copy holds that could be asked for: `read(name)` gives a file's bytes."""
    try:
        jobs = json.loads(read(JOBS)) if JOBS in names else []
        repos = json.loads(read(REPOS)) if REPOS in names else {}
    except (ValueError, KeyError, OSError):
        return {}
    repos = repos.get("repos") if isinstance(repos, dict) else {}
    return {
        "backup_jobs": sum(1 for j in jobs if isinstance(j, dict) and j.get("kind") != "config")
        if isinstance(jobs, list)
        else 0,
        "offsite": len(repos) if isinstance(repos, dict) else 0,
    }
