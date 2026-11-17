"""
Per-share access for non-admin users (SEC-10).

The file manager used to let any signed-in user act anywhere under the browse
roots except a short deny-list. Now a non-admin user can reach only:

- their home folder (read and write);
- shares the platform knows about (host shares on Unraid/TrueNAS, Kiboto Samba
  shares), at the level set for them: "none", "read" or "write";
- the folders above those, to list them (nothing else is shown in them).

Levels live in data/share_access.json:
    {"default_level": "write",
     "shares": {"media": {"default": "read", "users": {"alice": "write"}}}}
A user's level for a share is, in order: their entry under "users", the
share's Samba user lists (valid users / read list / write list; since Shares R4
only lists naming groups remain, the rest were folded into "users"), the share's
"default", the default for their role ("role_defaults", e.g. kids and guests), then
the global "default_level". A new install starts at "none" (B11, SEC-21); an install
upgraded from an earlier version had "write" written down for it, so nothing changes
for its families until an admin tightens it (the Security Advisor offers that).
"""

import logging
import os
import re
import threading
import time
from typing import Any, Optional

from backend import config
from backend.fsutil import atomic_write_json, read_json
from backend.ignored_errors import ignored

logger = logging.getLogger("Kiboto")

LEVELS = ("none", "read", "write")
_CACHE_TTL = 30.0
_cache: dict[str, Any] = {"ts": 0.0, "shares": []}
_lock = threading.Lock()


def _file() -> str:
    return os.path.join(config.DATA_DIR, "share_access.json")


def load_config() -> dict[str, Any]:
    data = read_json(_file(), {}) or {}
    level = data.get("default_level", "none")
    roles = data.get("role_defaults") or {}
    return {
        "default_level": level if level in LEVELS else "none",
        "role_defaults": {str(k): v for k, v in roles.items() if v in LEVELS} if isinstance(roles, dict) else {},
        "shares": {k: v for k, v in (data.get("shares") or {}).items() if isinstance(v, dict)},
    }


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {"default_level": cfg.get("default_level", "none"), "shares": {}}
    if clean["default_level"] not in LEVELS:
        raise ValueError("default_level must be none, read or write")
    roles = cfg.get("role_defaults") or {}
    if not isinstance(roles, dict) or any(v not in LEVELS for v in roles.values()):
        raise ValueError("role_defaults must map roles to none, read or write")
    if roles:
        clean["role_defaults"] = {str(k): v for k, v in roles.items()}
    for name, entry in (cfg.get("shares") or {}).items():
        if not re.match(r"^[A-Za-z0-9 ._-]{1,80}$", str(name)):
            raise ValueError(f"Invalid share name: {name!r}")
        users = {}
        for user, lvl in (entry.get("users") or {}).items():
            if lvl not in LEVELS or not re.match(r"^[A-Za-z0-9._-]{1,64}$", str(user)):
                raise ValueError(f"Invalid entry for {name}/{user}")
            users[str(user).lower()] = lvl
        default = entry.get("default")
        if default is not None and default not in LEVELS:
            raise ValueError(f"Invalid default for {name}")
        clean["shares"][name] = {"users": users, **({"default": default} if default else {})}
    atomic_write_json(_file(), clean)
    os.chmod(_file(), 0o600)
    invalidate()
    return clean


def grant(username: str, levels: dict[str, str]) -> dict[str, Any]:
    """Gives one person these levels on these shares ({share: "read" | "write"}), keeping the rest.
    For an invite's folders (SET-19)."""
    cfg = load_config()
    for share, level in levels.items():
        entry = cfg["shares"].setdefault(share, {"users": {}})
        entry.setdefault("users", {})[username.lower()] = level
    return save_config(cfg)


def grant_many(share: str, people: dict[str, str]) -> dict[str, Any]:
    """Gives these people these levels on one share ({username: "read" | "write"}), keeping the rest.
    For the people chosen when a share is made (Shares R4)."""
    cfg = load_config()
    entry = cfg["shares"].setdefault(share, {"users": {}})
    for username, level in people.items():
        entry.setdefault("users", {})[username.lower()] = level
    return save_config(cfg)


def share_level(cfg: dict[str, Any], share: str, username: str, role_id: str) -> str:
    """The level share access gives this person on this share, Samba's own lists left out
    (the lists Kiboto writes into smb.conf come from this: B11, SEC-28)."""
    entry = cfg["shares"].get(share, {})
    return (
        (entry.get("users") or {}).get(username.lower())
        or entry.get("default")
        or cfg["role_defaults"].get(str(role_id or ""))
        or cfg["default_level"]
    )


# Roles that open every folder: administrators and storage admins (Users A12, SET-19)
ADMIN_ROLES = ("superadmin", "storage_admin")
# Hosts that run the network shares themselves (Unraid, TrueNAS...): Kiboto decides Files only
OWN_NETWORK = ("zettos", "generic_linux")


def levels_for_person(user: dict[str, Any], shares: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, str]:
    """{share name: level} for one person, in the order grants_for() uses; administrators "write"."""
    name = str(user.get("username") or "").lower()
    role = str(user.get("role_id") or "")
    if role in ADMIN_ROLES:
        return {s["name"]: "write" for s in shares}
    role_default = cfg["role_defaults"].get(role)
    out = {}
    for share in shares:
        entry = cfg["shares"].get(share["name"], {})
        out[share["name"]] = (
            (entry.get("users") or {}).get(name)
            or _samba_level(share["samba"], name)
            or entry.get("default")
            or role_default
            or cfg["default_level"]
        )
    return out


def who_can_open(users: list[dict[str, Any]], platform: str = "") -> dict[str, Any]:
    """Each shared folder with every active person's level (SET-22, Shares 2). "host" names the
    system that decides the network side when that is not Kiboto."""
    cfg = load_config()
    shares = known_shares()
    people = [u for u in users if (u.get("status") or "active") == "active"]
    levels = {str(u.get("username")): levels_for_person(u, shares, cfg) for u in people}
    return {
        "host": "" if not platform or platform in OWN_NETWORK else platform,
        "shares": [
            {
                "name": sh["name"],
                "people": [
                    {
                        "username": u.get("username"),
                        "name": u.get("display_name") or u.get("username"),
                        "role": u.get("role_id"),
                        "admin": str(u.get("role_id") or "") in ADMIN_ROLES,
                        "level": levels[str(u.get("username"))][sh["name"]],
                    }
                    for u in people
                ],
            }
            for sh in shares
        ],
    }


def invalidate() -> None:
    with _lock:
        _cache["ts"] = 0.0


def _split_users(value: str | None) -> set:
    return {u.lower() for u in re.split(r"[,\s]+", value or "") if u and not u.startswith(("@", "+", "&"))}


def known_shares() -> list[dict[str, Any]]:
    """[{name, path, samba: {valid, read, write, read_only, guest}}] for every share the platform reports."""
    now = time.time()
    with _lock:
        if now - _cache["ts"] < _CACHE_TTL:
            return list(_cache["shares"])
    shares: dict[str, dict[str, Any]] = {}
    try:
        from backend.hardware.pal_storage import get_storage_platform

        for s in get_storage_platform().list_shares():
            if s.mountpoint:
                shares[s.name] = {"name": s.name, "path": os.path.realpath(s.mountpoint), "samba": None}
    except Exception:
        ignored("backend.services.share_access.known_shares")
    try:
        from backend.services.samba_engine import get_samba_engine

        for s in get_samba_engine().list_shares():
            shares[s.name] = {
                "name": s.name,
                "path": os.path.realpath(s.path),
                "samba": {
                    "valid": _split_users(s.valid_users),
                    "read": _split_users(s.read_list),
                    "write": _split_users(s.write_list),
                    "read_only": bool(s.read_only),
                },
            }
    except Exception:
        ignored("backend.services.share_access.known_shares")
    result = list(shares.values())
    with _lock:
        _cache.update(ts=now, shares=result)
    return result


def _samba_level(samba: dict[str, Any] | None, username: str) -> str | None:
    if not samba or not (samba["valid"] or samba["read"] or samba["write"]):
        return None
    if username in samba["write"]:
        return "write"
    if username in samba["read"]:
        return "read"
    if samba["valid"] and username not in samba["valid"]:
        return "none"
    return "read" if samba["read_only"] else "write"


def _user(username: str) -> dict[str, Any]:
    try:
        from backend.users_db import get_user_by_username

        return get_user_by_username(username) or {}
    except Exception:
        return {}


def _home_for(username: str, user: dict[str, Any] | None = None) -> str | None:
    user = user if user is not None else _user(username)
    home = user.get("home_directory")
    home = home or os.path.join(getattr(config, "POOL_PATH", "/mnt/user"), "homes", username)
    return os.path.realpath(home)


def grants_for(username: str) -> list[tuple[str, str]]:
    """[(path, level)] the user may use, most specific first."""
    username = (username or "").lower()
    if not username:
        return []
    cfg = load_config()
    grants: list[tuple[str, str]] = []
    user = _user(username)
    role_default = cfg["role_defaults"].get(str(user.get("role_id") or ""))
    home = _home_for(username, user)
    if home:
        grants.append((home, "write"))
    by_share: dict[str, str] = {}
    for share in known_shares():
        entry = cfg["shares"].get(share["name"], {})
        level = (
            (entry.get("users") or {}).get(username)
            or _samba_level(share["samba"], username)
            or entry.get("default")
            or role_default
            or cfg["default_level"]
        )
        grants.append((share["path"], level))
        by_share[share["name"]] = level
    # an open encrypted folder (FEAT-13) is reached as its share is
    # (and only by the people on its own list, when it has one: NSEC-5)
    from backend.services.encrypted_index import grant_paths, grant_people

    people = grant_people()
    for plain, share_name in grant_paths().items():
        who = people.get(plain)
        on_list = who is None or username.lower() in {p.lower() for p in who}
        grants.append((plain, by_share.get(share_name, "none") if on_list else "none"))
    grants.sort(key=lambda g: len(g[0]), reverse=True)
    return grants


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def file_level(username: str, path: str, grants: list[tuple[str, str]]) -> str:
    """level_for() for a file path that is already canonical, with the user's grants given.

    Touches no disk: used for paths stored in the AI index (resolved when indexed), where
    resolving them again would wake sleeping drives. Files are never "list".
    """
    parts = [x for x in path.split("/") if x]
    user = (username or "").lower()
    for i, part in enumerate(parts[:-1]):
        if part == "homes" and parts[i + 1].lower() == user:
            return "write"
    for root, level in grants:
        if _inside(path, root):
            return level
    return "none"


def level_for(username: str, real_path: str) -> str:
    """ "write", "read", "list" (a folder above a granted share) or "none"."""
    real = os.path.realpath(real_path)
    # Any ".../homes/<username>" folder is the user's own (same rule as the home check).
    parts = [x for x in real.split("/") if x]
    user = (username or "").lower()
    for i, part in enumerate(parts[:-1]):
        if part == "homes" and parts[i + 1].lower() == user:
            return "write"
    if parts and parts[-1] == "homes" and os.path.isdir(real):
        return "list"
    grants = grants_for(username)
    for root, level in grants:
        if _inside(real, root):
            return level
    if any(_inside(root, real) for root, lvl in grants if lvl != "none") and os.path.isdir(real):
        return "list"
    return "none"


USER_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _before_fold_file() -> str:
    return os.path.join(config.DATA_DIR, "share_lists_before_fold.json")


def fold_share_lists(engine: Any = None, users: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Shares R4 (owner, 16 Nov 2026 evening): one access list. A share's own Samba lists (valid
    users, read list, write list) are written into the share access table, person by person, and
    then cleared, so the table on Users is the only place that decides, for the network and Files
    alike. What each person could do stays the same: their own cell in the table already decided
    Files and is kept; for everyone else the share's lists decide, as they did over the network.
    Administrators open every folder anyway (and are in the network list Kiboto writes).

    The old lists are copied to share_lists_before_fold.json first. Lists that name a group
    (@group, +group, &group) cannot be said person by person and are left as they are.
    Does nothing once no share has lists of its own, so it runs at every start."""
    import time as _time

    from backend.services.samba_engine import get_samba_engine, refresh_access

    engine = engine or get_samba_engine()
    if users is None:
        from backend.users_db import list_users

        users = list_users()
    cfg = load_config()
    folded: list[str] = []
    kept: list[dict[str, str]] = []
    before: dict[str, Any] = {}
    changed: dict[str, dict[str, str]] = {}
    for share in engine.list_shares():
        raw = {f: (getattr(share, f) or "").strip() for f in ("valid_users", "read_list", "write_list")}
        if not any(raw.values()):
            continue
        names = [n for v in raw.values() for n in re.split(r"[,\s]+", v) if n]
        if any(n.startswith(("@", "+", "&")) for n in names):
            kept.append({"name": share.name, "why": "groups"})
            continue
        samba = {
            "valid": _split_users(raw["valid_users"]),
            "read": _split_users(raw["read_list"]),
            "write": _split_users(raw["write_list"]),
            "read_only": bool(share.read_only),
        }
        entry = cfg["shares"].setdefault(share.name, {"users": {}})
        cells = entry.setdefault("users", {})
        for u in users:
            name = str(u.get("username") or "").lower()
            role = str(u.get("role_id") or "")
            if (u.get("status") or "active") != "active" or not USER_NAME.match(name) or role in ADMIN_ROLES:
                continue
            if name in cells:
                continue  # their own cell already decided Files: kept
            level = _samba_level(samba, name)
            if level and level != share_level(cfg, share.name, name, role):
                cells[name] = level
                changed.setdefault(share.name, {})[name] = level
        before[share.name] = {**raw, "read_only": bool(share.read_only), "folded_at": _time.time()}
        folded.append(share.name)
    if not folded:
        return {"folded": [], "kept": kept, "changed": {}}
    kept_before = read_json(_before_fold_file(), {}) or {}
    atomic_write_json(_before_fold_file(), {**kept_before, **before})  # the old lists, before anything changes
    os.chmod(_before_fold_file(), 0o600)
    save_config(cfg)
    for share in engine.list_shares():
        if share.name in folded:
            share.valid_users = share.read_list = share.write_list = None
            engine.add_or_update_share(share)
    refresh_access()
    logger.info("Shares R4: folded the own lists of %s into share access (%s)", ", ".join(folded), changed)
    return {"folded": folded, "kept": kept, "changed": changed}
