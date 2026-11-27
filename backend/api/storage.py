"""
Kiboto - Storage Subsystem API Routes
Platform Abstraction Layer (PAL) endpoints for storage pools, array topology,
and network shares (Samba/NFS/WebDAV).
"""

import asyncio
import logging
import os
import shutil
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel, Field

from backend import config
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import require_confirmation
from backend.errors import ApiError, error_response, said
from backend.fsutil import single_name
from backend.hardware.pal import pool_rules, system_disk
from backend.hardware.pal.base import PoolUsedElsewhere
from backend.hardware.pal.pool_rules import POOL_ID_PATTERN, POOL_NAME_PATTERN
from backend.hardware.pal.pool_rules import import_mount as _mount_point
from backend.hardware.pal_storage import (
    PlatformCapabilityError,
    get_storage_platform,
)
from backend.ignored_errors import ignored
from backend.logging_config import one_line

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storage", tags=["Storage Subsystem & PAL"])


# A pool's name as it reaches zpool/btrfs as an argument: no leading dash ("-a" would be an
# option, export -a exports every pool), no spaces (CodeQL command-line injection)
# a pool's id as the storage tools take it: also no leading / and no .. (pool_rules.pool_id), here
# as in the host door, for a Kiboto that runs the tools itself
PoolId = Annotated[str, Path(pattern=POOL_ID_PATTERN), AfterValidator(pool_rules.pool_id)]


class StorageScrubRequest(BaseModel):
    # pool names go to zpool/btrfs as arguments: no leading dash, no spaces
    pool_id: Annotated[str, AfterValidator(pool_rules.pool_id)] = "unraid_array"
    action: str = Field("start", pattern=r"^[a-z_]{1,16}$")


class StoragePoolCreateRequest(BaseModel):
    name: str
    fs_type: str = "btrfs"
    profile: str = "raid1"
    disks: list[str] = Field(default_factory=list)
    mountpoint: str = ""
    # Formatting is irreversible (SEC-08): the user types the pool name and their password,
    # and must say so explicitly when the disks still hold data.
    confirm_name: str = ""
    current_password: str = ""
    erase_existing_data: bool = False


class StoragePoolExportRequest(BaseModel):
    force: bool = False


class StoragePoolImportRequest(BaseModel):
    pool_id: str = Field(..., pattern=POOL_NAME_PATTERN)  # a name, never an option or a path
    fs_type: str = Field("zfs", pattern=r"^[a-z0-9]{1,16}$")
    target_mount: Annotated[str | None, AfterValidator(_mount_point)] = None
    guid: str = Field("", pattern=r"^[0-9]{0,24}$")  # the id "look for pools" showed: two pools can share a name
    force: bool = False  # only after the person was told the pool was last used by another system


class StorageShareCreateRequest(BaseModel):
    name: str
    path: str = ""
    comment: str = ""
    security: str = "private"  # B11 (SEC-22): guest access only when chosen
    read_only: bool = False
    export_smb: bool = True
    export_nfs: bool = False
    quota_gb: int | None = Field(default=0, description="Storage quota in GB (0 = unlimited)")
    user_permissions: dict[str, str] | None = Field(
        default_factory=dict, description="User permission matrix: {username: 'rw'|'ro'|'deny'}"
    )
    # every NFS client writes as the file server's user, as SMB does (nfs_engine.FILE_SERVER_UID)
    nfs_squash: str = Field(default="all_squash", description="'all_squash', 'root_squash' or 'no_root_squash'")
    nfs_anonuid: int = Field(default=65534, description="UID squashed clients write as (the file server's user)")
    nfs_anongid: int = Field(default=100, description="GID squashed clients write as (the file server's group)")
    nfs_sync: bool = Field(default=True, description="True for synchronous commits (ACID), False for async")
    nfs_clients: str = Field(default="", description="Allowed client host or CIDR subnet; empty = this home network")
    timemachine: bool = Field(default=False, description="A Time Machine destination; needs SMB and a size limit")
    nfs_allow_everyone: bool = Field(default=False, description="True to export to every host (*), chosen explicitly")


def nfs_clients_for(clients: str, allow_everyone: bool) -> str:
    """Who an NFS export reaches (B11, SEC-23): what was asked for, this home network when nothing
    was, and every host ("*") only when that was chosen explicitly."""
    from backend.services.nfs_engine import home_network

    clients = (clients or "").strip()
    if clients in ("", "*") and not allow_everyone:
        return home_network()
    return clients


class StoragePoolRenameRequest(BaseModel):
    new_name: str = Field(
        ..., min_length=1, max_length=64, pattern=POOL_NAME_PATTERN, description="New name for storage pool"
    )


SingleName = Annotated[str, AfterValidator(single_name)]


class StorageSnapshotCreateRequest(BaseModel):
    subvolume: SingleName = "@shares"
    snapshot_name: SingleName
    readonly: bool = True
    worm_mode: str | None = Field(default=None, description="Two-Tier WORM mode: 'governance' or 'compliance'")
    retention_days: int | None = Field(
        default=None, ge=1, le=3650, description="WORM retention period in days (1-3650)"
    )


class StorageSnapshotBreakGlassDeleteRequest(BaseModel):
    snapshot_name: SingleName
    reason: str = Field(
        ..., min_length=5, description="Mandatory audit justification for breaking governance WORM lock"
    )


@router.get("/platform", dependencies=[Depends(require_scope("storage:read", "shares:read", "system:view"))])
def get_storage_platform_info() -> dict[str, Any]:
    """
    Returns platform classification (Unraid, TrueNAS, Generic Linux),
    capabilities (observer mode vs active provisioner), and storage busy state.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    return {
        "platform": adapter.get_platform_type().value,
        "capabilities": caps.model_dump(),
        "is_busy": adapter.is_storage_busy(),
        # looking for pools reads the label of every drive; in a container install it finds no
        # device and an import cannot work, so the page does not offer it there (SET-09)
        "can_look_for_pools": bool(caps.can_import_pools) and not _in_container(),
    }


def _in_container() -> bool:
    from backend import runtime

    return runtime.in_container()


@router.get("/pools", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def get_storage_pools() -> dict[str, Any]:
    """
    Returns hierarchical storage pool and array topology, including parity protection,
    data disks, SSD cache tiers, capacity gauges, and health statuses.
    """
    adapter = get_storage_platform()
    pools = adapter.list_pools()
    return {
        "platform": adapter.get_platform_type().value,
        "is_observer_mode": adapter.get_capabilities().is_observer_mode,
        # what this platform can do with a pool: the page draws only those buttons (SET-06)
        "can_trigger_scrub": bool(adapter.get_capabilities().can_trigger_scrub),
        "can_export_pools": bool(adapter.get_capabilities().can_export_pools),
        "is_busy": adapter.is_storage_busy(),
        "pools": [_with_erasable(p.model_dump(), p, adapter) for p in pools],
        "system_disk_kept_free": system_disk.applies(),  # no shares there: Setup asks for a pool
    }


def _with_erasable(row: dict[str, Any], pool: Any, adapter: Any) -> dict[str, Any]:
    """Whether "Delete pool and erase its drives" is offered (S29): a host Kiboto manages, and a
    ZFS, Btrfs or mdadm pool, whose own tool names its drives."""
    from backend.hardware.pal import pool_erase

    caps = adapter.get_capabilities()
    row["erasable"] = bool(caps.can_destroy_pools and not caps.is_observer_mode and pool_erase.kind_of(pool))
    # "Replace a drive": a pool Kiboto manages whose own tool rebuilds onto a new drive
    row["replaceable"] = bool(
        caps.can_destroy_pools and not caps.is_observer_mode and pool.fs_type in ("zfs", "btrfs") and not pool.read_only
    )
    row["growable"] = row["replaceable"]  # "Add a drive": the same pools, each grown with its own tool
    return row


@router.get("/shares", dependencies=[Depends(require_scope("storage:read", "shares:read", "system:view"))])
def get_storage_shares() -> dict[str, Any]:
    """
    Returns network shares (Samba, NFS, WebDAV) with comment, security level,
    cache tiering settings, and live disk usage statistics.
    """
    adapter = get_storage_platform()
    shares = adapter.list_shares()
    return {
        "platform": adapter.get_platform_type().value,
        "is_observer_mode": adapter.get_capabilities().is_observer_mode,
        "shares": [s.model_dump() for s in shares],
    }


@router.get("/overview", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def get_storage_overview() -> dict[str, Any]:
    """
    Returns unified storage overview: pools, shares, platform info, and physical disk inventories.
    """
    from backend.hardware.hal import DiskDiscoveryHAL

    adapter = get_storage_platform()
    pools = adapter.list_pools()
    shares = adapter.list_shares()
    caps = adapter.get_capabilities()

    assigned_devs = set()
    for p in pools:
        for m in getattr(p, "members", []):
            name = (getattr(m, "device", "") or getattr(m, "name", "")).replace("/dev/", "")
            if name:
                assigned_devs.add(name)

    records = DiskDiscoveryHAL.discover_physical_disks()
    all_disks = []
    unassigned = []
    for r in records:
        is_assigned = r.dev_name in assigned_devs or r.role == "os"
        d_dict = {
            "dev": r.dev_name,
            "name": r.dev_name,
            "size": getattr(r, "size_formatted", getattr(r, "size_human", "0 GB")),
            "size_bytes": r.size_bytes,
            "model": r.model,
            "serial": r.serial,
            "role": r.role,
            "transport": r.transport,
            "assigned": is_assigned,
        }
        all_disks.append(d_dict)
        if not is_assigned:
            unassigned.append(d_dict)

    return {
        "platform": adapter.get_platform_type().value,
        "is_observer_mode": caps.is_observer_mode,
        "is_busy": adapter.is_storage_busy(),
        "pools": [p.model_dump() for p in pools],
        "shares": [s.model_dump() for s in shares],
        "disks": all_disks,
        "unassigned_disks": unassigned,
    }


@router.get("/disks", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def get_storage_disks() -> dict[str, Any]:
    """Returns detected physical disks discovered via DiskDiscoveryHAL."""
    from backend.hardware.hal import DiskDiscoveryHAL

    records = DiskDiscoveryHAL.discover_physical_disks()
    return {
        "disks": [
            {
                "dev": r.dev_name,
                "name": r.dev_name,
                "size": getattr(r, "size_formatted", getattr(r, "size_human", "0 GB")),
                "size_bytes": r.size_bytes,
                "model": r.model,
                "serial": r.serial,
                "role": r.role,
                "transport": r.transport,
            }
            for r in records
        ]
    }


@router.post("/scrub", dependencies=[Depends(require_scope("storage:admin"))])
def trigger_storage_scrub(req: StorageScrubRequest) -> dict[str, Any]:
    """
    Initiates or monitors non-destructive array parity check or filesystem scrub.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if not caps.can_trigger_scrub:
        raise HTTPException(
            status_code=403,
            detail=f"Storage scrub is disabled on {adapter.get_platform_type().value}.",
        )
    try:
        res = adapter.trigger_scrub(pool_id=req.pool_id, action=req.action)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    # a check that did not start is an error, not an answer with "status": "error" under 200 (SET-06)
    if isinstance(res, dict) and res.get("status") in ("error", "unsupported"):
        why = str(res.get("message") or res.get("output") or "The check could not be started.").strip()
        raise HTTPException(status_code=400 if res["status"] == "unsupported" else 502, detail=why)
    return res


@router.get("/schedule", dependencies=[Depends(require_scope("storage:read"))])
def get_storage_schedule_config() -> dict[str, Any]:
    """Retrieves current automated SMART self-test and storage scrub schedule."""
    from backend.services.scheduler import get_smart_schedule

    return get_smart_schedule()


@router.put("/schedule", dependencies=[Depends(require_scope("storage:admin"))])
def update_storage_schedule_config(req: dict[str, Any]) -> dict[str, Any]:
    """Updates automated SMART self-test and storage scrub schedule."""
    from backend.services.scheduler import save_smart_schedule

    return save_smart_schedule(req)


@router.post(
    "/pools",
    dependencies=[Depends(require_scope("storage:admin")), Depends(require_confirmation("storage.pool.create"))],
    response_model=None,  # a dict, or the refusal as its own JSON response
)
def create_storage_pool(
    req: StoragePoolCreateRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any] | JSONResponse:
    """
    Creates a new storage pool. In Observer Mode (e.g. Unraid, TrueNAS),
    this operation is strictly rejected to protect host array parity.
    """
    from backend.hardware.disk_safety import check_disks
    from backend.hardware.pal import pool_rules
    from backend.passwords import verify_password
    from backend.users_db import get_user_by_id

    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}. "
            "Storage pools and RAID arrays must be managed authoritatively by the host OS.",
        )
    try:
        pool_rules.new_pool_name(req.name or "")
        mountpoint = pool_rules.new_pool_mount(req.mountpoint)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        layout = pool_rules.pool_layout(req.fs_type, req.profile, len(req.disks))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if req.confirm_name != req.name:
        raise HTTPException(status_code=400, detail="Type the pool name to confirm that the disks will be erased.")
    user = get_user_by_id(principal.user_id) if principal and principal.user_id else None
    if not user or not verify_password(req.current_password or "", user.get("password_hash", "")):
        raise HTTPException(status_code=403, detail="Current password is incorrect.")

    resolve = getattr(adapter, "_resolve_disk_path", None)
    disks = [resolve(d) if resolve else (d if d.startswith("/") else f"/dev/{d}") for d in req.disks]
    problems = check_disks(disks, allow_erase=req.erase_existing_data)
    if problems:
        return error_response(
            409,
            "These disks can't be formatted: " + "; ".join(f"{p['disk']}: {p['reason']}" for p in problems),
            error="disks_not_safe",
            problems=problems,
            erasable=all(p.get("erasable") == "true" for p in problems),
        )
    logger.warning(
        "[Storage] Creating pool '%s' (%s) on %s", one_line(req.name), one_line(req.fs_type), one_line(", ".join(disks))
    )
    try:
        made = adapter.create_pool(
            name=req.name,
            fs_type=req.fs_type,
            profile=layout,
            disks=req.disks,
            mountpoint=mountpoint,
        )
        _first_share_on_the_pool(adapter)
        return made
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except RuntimeError as e:
        logger.error(f"[Storage] Pool '{one_line(req.name)}' was not created: {one_line(e)}")
        raise HTTPException(status_code=500, detail=f"The pool was not created: {e}") from e


def _first_share_on_the_pool(adapter: Any) -> None:
    """On a machine set up for Kiboto the first pool gets the shared folder other installs start with."""
    from backend.services import pool_places
    from backend.services.samba_engine import get_samba_engine

    try:
        pool_places.settle()  # people's home folders go on the first pool too
        made = system_disk.default_share_after_pool(adapter, bool(get_samba_engine().list_shares()))
    except (ValueError, OSError, RuntimeError) as e:
        logger.warning("[Storage] The first shared folder was not made on the new pool: %s", one_line(e))
        return
    if made:
        logger.info("[Storage] Shared folder %s made on the first pool", made)


class ShareAccessUpdate(BaseModel):
    # Left out = keep what is saved now (the file manager page sends only shares).
    default_level: str | None = None
    role_defaults: dict[str, str] | None = None
    shares: dict[str, dict[str, Any]] = Field(default_factory=dict)


@router.get("/share-access", dependencies=[Depends(require_scope("shares:manage"))])
def get_share_access() -> dict[str, Any]:
    """Who can use which share in the file manager (SEC-10)."""
    from backend.services.share_access import known_shares, load_config

    cfg = load_config()
    return {
        "default_level": cfg["default_level"],
        "role_defaults": cfg["role_defaults"],
        "levels": ["none", "read", "write"],
        "shares": [
            {"name": sh["name"], "path": sh["path"], **cfg["shares"].get(sh["name"], {"users": {}})}
            for sh in known_shares()
        ],
    }


@router.get("/connect")
def get_connect_address(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """The address a computer at home opens the shared folders with (SET-22, Shares 3): the NAS's
    own address on the home network, not the one this page happens to be reached through."""
    from backend.hardware.net.topology import read_ip

    try:
        ip = str(read_ip() or "")
    except (OSError, ValueError, RuntimeError):
        ip = ""
    return {"address": ip}


@router.get("/share-access/who", dependencies=[Depends(require_scope("shares:manage"))])
def get_share_who() -> dict[str, Any]:
    """Who can really open each shared folder: administrators and role defaults included (SET-22)."""
    from backend.hardware.pal_storage import get_storage_platform
    from backend.services.share_access import who_can_open
    from backend.users_db import list_users

    try:
        platform = str(get_storage_platform().get_platform_type().value)
    except (AttributeError, ValueError, OSError, RuntimeError):
        platform = ""
    return who_can_open(list_users(), platform)


@router.put("/share-access", dependencies=[Depends(require_scope("shares:manage"))])
def put_share_access(req: ShareAccessUpdate) -> dict[str, Any]:
    from backend.services.share_access import load_config, save_config

    current = load_config()
    body = req.model_dump()
    body["default_level"] = body["default_level"] or current["default_level"]
    if body["role_defaults"] is None:
        body["role_defaults"] = current["role_defaults"]
    try:
        saved = save_config(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    from backend.services.samba_engine import refresh_access

    refresh_access()  # SMB follows share access (SEC-28)
    return saved


SHARE_LEVELS = {"rw": "write", "ro": "read", "deny": "none"}  # the create dialog's words, in share access


@router.post("/shares", dependencies=[Depends(require_scope("shares:manage"))])
def create_storage_share(req: StorageShareCreateRequest) -> dict[str, Any]:
    """
    Creates a new network share. In Observer Mode (e.g. Unraid, TrueNAS),
    shares must be created via the host WebGUI or configuration files.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}. "
            "Network shares must be configured via host OS to ensure proper Samba driver integration.",
        )
    if req.timemachine and not req.export_smb:
        raise HTTPException(status_code=400, detail="A Time Machine folder is reached over SMB: keep SMB on for it.")
    if req.timemachine and not (req.quota_gb or 0) > 0:
        raise HTTPException(
            status_code=400,
            detail="Give a Time Machine folder a size limit, so the backups cannot fill the storage.",
        )
    try:
        created = adapter.create_share(
            name=req.name,
            path=req.path,
            comment=req.comment,
            security=req.security,
            read_only=req.read_only,
            export_smb=req.export_smb,
            export_nfs=req.export_nfs,
            quota_gb=req.quota_gb or 0,
            user_permissions=req.user_permissions or {},
            nfs_squash=req.nfs_squash,
            nfs_anonuid=req.nfs_anonuid,
            nfs_anongid=req.nfs_anongid,
            nfs_sync=req.nfs_sync,
            nfs_clients=nfs_clients_for(req.nfs_clients, req.nfs_allow_everyone),
        )
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        # a folder outside the allowed places, a reserved name, a bad client list: say which (SET-01),
        # in the reader's language where the refusal says how
        raise ApiError(400, str(e), "invalid_share", text=getattr(e, "text", None)) from e
    people = {u: SHARE_LEVELS[p] for u, p in (req.user_permissions or {}).items() if p in SHARE_LEVELS}
    if people:
        from backend.services.samba_engine import refresh_access
        from backend.services.share_access import grant_many

        grant_many(req.name, people)  # Shares R4: the one access list, for the network and Files
        refresh_access()
    if req.timemachine:
        # no default snapshots: Time Machine deletes its own old backups to make room, and a
        # snapshot would keep what it deleted until the pool is full
        _make_time_machine(req.name, int(req.quota_gb or 0))
        return created
    try:
        from backend.services import snapshot_service

        snapshot_service.ensure_default(req.name)  # snapshots on by default (FEAT-02)
    except Exception as e:
        logger.warning(f"[Storage] No default snapshots for {one_line(req.name)}: {one_line(e)}")
    return created


GIB = 1024**3


def _time_machine_too_big(share: Any, size_gb: int) -> str:
    """Why this Time Machine size limit can't hold on the folder's pool: more than the pool can
    give it, so Time Machine would fill the pool (and every folder and app on it) first. "" when
    it fits, or when the folder's room can't be told."""
    path = str(getattr(share, "path", "") or "")
    if not size_gb or not path or not os.path.isdir(path):
        return ""
    try:
        room = shutil.disk_usage(path).total  # what this folder has used plus what it may still use
    except OSError:
        return ""
    if size_gb * GIB <= room:
        return ""
    most = max(1, int(room // GIB))
    return (
        f"the pool it is on holds about {most} GB, so Time Machine would fill it before reaching "
        f"{size_gb} GB. Give it at most {most} GB"
    )


def _make_time_machine(name: str, size_gb: int) -> None:
    """Marks the share just created as a Time Machine destination and keeps what it was created
    with (its people lists, read-only). The page used to send a second request that replaced them,
    without a size limit, and hid its failure (SET-01)."""
    from backend.services import nas_name
    from backend.services.samba_engine import get_samba_engine

    engine = get_samba_engine()
    share = engine.get_share(name)
    problem = f"The folder {name} is shared, but Time Machine could not be turned on for it"
    if share is None:
        raise HTTPException(status_code=400, detail=f"{problem}.")
    why = _time_machine_too_big(share, size_gb)
    if why:
        raise HTTPException(status_code=400, detail=f"{problem}: {why}.")
    try:
        engine.add_or_update_share(share.model_copy(update={"timemachine": True, "timemachine_quota_gb": size_gb}))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{problem}: {e}") from e
    nas_name.refresh()  # a Time Machine share is announced to Macs (FEAT-09)


class TimeMachineUpdate(BaseModel):
    size_gb: int = Field(..., ge=0, le=1_000_000, description="The size limit in GB; 0 stops Mac backups to the folder")


@router.get("/time-machine", dependencies=[Depends(require_scope("shares:manage"))])
def get_time_machine_folders() -> dict[str, Any]:
    """Shares R3: the folders Macs back up to, with their size limits, where Kiboto runs the shares."""
    adapter = get_storage_platform()
    if adapter.get_capabilities().is_observer_mode:
        return {"managed": False, "folders": []}
    from backend.services.samba_engine import get_samba_engine

    folders = [
        {"name": s.name, "size_gb": int(s.timemachine_quota_gb or 0)}
        for s in get_samba_engine().list_shares()
        if s.timemachine
    ]
    return {"managed": True, "folders": folders}


@router.put("/shares/{name}/time-machine", dependencies=[Depends(require_scope("shares:manage"))])
def put_time_machine(name: str, req: TimeMachineUpdate) -> dict[str, Any]:
    """Shares R3: changes a folder's Mac-backup size limit, or stops Mac backups to it, keeping every
    other setting of the share (the share route replaces the whole share)."""
    from backend.services import nas_name
    from backend.services.samba_engine import get_samba_engine

    if get_storage_platform().get_capabilities().is_observer_mode:
        raise HTTPException(status_code=403, detail="The host runs the shares here; change Time Machine there.")
    engine = get_samba_engine()
    share = engine.get_share(name)
    if share is None:
        raise HTTPException(status_code=404, detail=f"There is no shared folder {name}.")
    why = _time_machine_too_big(share, req.size_gb)
    if why:
        raise HTTPException(status_code=400, detail=f"The size limit was not changed: {why}.")
    update = (
        {"timemachine": True, "timemachine_quota_gb": req.size_gb}
        if req.size_gb
        else {"timemachine": False, "timemachine_quota_gb": None}
    )
    try:
        engine.add_or_update_share(share.model_copy(update=update))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    nas_name.refresh()  # Macs see the change in the folders they are offered
    return {"name": name, "size_gb": req.size_gb, "timemachine": bool(req.size_gb)}


class ShareCompressionRequest(BaseModel):
    value: str = Field(
        ...,
        pattern=r"^[a-z0-9][a-z0-9-]{0,15}$",
        description="off, lz4, zstd, zstd-fast, gzip (ZFS) or off, zstd, lzo, zlib (btrfs)",
    )


def _share_path(name: str) -> tuple[Any, str]:
    adapter = get_storage_platform()
    for share in adapter.list_shares():
        if share.name == name and share.mountpoint:
            return adapter, share.mountpoint
    raise HTTPException(status_code=404, detail=f"No share named {name}")


def _share_asleep(path: str) -> bool:
    try:
        from backend.services.rag_standby import is_backing_disk_in_standby

        return bool(is_backing_disk_in_standby(path))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        ignored("backend.api.storage._share_asleep")
        return False


@router.get("/shares/{name}/compression", dependencies=[Depends(require_scope("storage:read", "shares:manage"))])
def get_share_compression(name: str) -> dict[str, Any]:
    """What compression a share's data uses now, the ratio where the filesystem reports one, and
    what can be chosen (FEAT-15). A sleeping disk is not woken to read a btrfs folder's setting."""
    from backend.hardware import share_compression

    adapter, path = _share_path(name)
    info = share_compression.read(path, asleep=_share_asleep)
    if adapter.get_capabilities().is_observer_mode:
        info["read_only"] = True
        info["reason"] = f"Set compression in {adapter.get_platform_type().value}'s own settings"
    return info


@router.put("/shares/{name}/compression", dependencies=[Depends(require_scope("shares:manage", "storage:admin"))])
def set_share_compression(name: str, req: ShareCompressionRequest) -> dict[str, Any]:
    """Change a share's compression; it applies to data written from now on (FEAT-15)."""
    from backend.hardware import share_compression

    adapter, path = _share_path(name)
    if adapter.get_capabilities().is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Compression is managed by {adapter.get_platform_type().value}; change it in its own settings",
        )
    try:
        return share_compression.set_value(path, req.value, asleep=_share_asleep)
    except share_compression.CompressionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post("/pools/{pool_id}/rename", dependencies=[Depends(require_scope("storage:admin"))])
def rename_storage_pool(pool_id: PoolId, req: StoragePoolRenameRequest) -> dict[str, Any]:
    """
    Renames an existing storage pool (OpenZFS or Btrfs) and creates an atomic
    backwards-compatibility symlink to preserve Docker container volume mounts.
    Forbidden in Observer Mode.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}. "
            "Storage pools and array identifiers must be managed authoritatively by the host OS.",
        )
    try:
        return adapter.rename_pool(pool_id=pool_id, new_name=req.new_name)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:  # the rename did not happen: say why (a 500 hides its reason)
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete(
    "/pools/{pool_id}",
    dependencies=[Depends(require_scope("storage:admin")), Depends(require_confirmation("storage.pool.delete"))],
)
def delete_storage_pool(pool_id: PoolId) -> dict[str, Any]:
    """
    Destroys/unmounts a storage pool. Forbidden in Observer Mode.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}.",
        )
    try:
        return adapter.destroy_pool(pool_id=pool_id)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


class DriveReplaceRequest(BaseModel):
    old: str = Field(..., min_length=1, max_length=256)
    new: str = Field(..., min_length=1, max_length=256)


@router.get("/pools/{pool_id}/replace", dependencies=[Depends(require_scope("storage:admin"))])
def get_drive_replace_plan(pool_id: PoolId) -> dict[str, Any]:
    """Whether the pool can rebuild onto a new drive, its drives, the empty drives that fit, and a
    rebuild that is running now."""
    from backend.services import edition_features

    try:
        return {**get_storage_platform().replace_plan(pool_id), "edition": edition_features.state("drive_replace")}
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post(
    "/pools/{pool_id}/replace",
    dependencies=[Depends(require_scope("storage:admin")), Depends(require_confirmation("storage.drive.replace"))],
)
def replace_pool_drive(
    pool_id: PoolId,
    req: DriveReplaceRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Starts rebuilding one of the pool's drives onto an empty one. Nothing is erased: the new drive
    must hold nothing, and the pool's own tool refuses one that is too small."""
    try:
        res = get_storage_platform().replace_drive(pool_id, req.old, req.new)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if not res.get("started"):
        raise HTTPException(status_code=409, detail=str(res.get("message") or "The drive could not be replaced."))
    from backend.users_db import log_security_event

    log_security_event(
        "storage.drive_replace",
        "success",
        actor_id=getattr(principal, "user_id", None),
        actor_username=principal.username,
        actor_ip=request.client.host if request.client else "",
        details={"pool": pool_id, "old": res.get("old", ""), "new": res.get("new", "")},
    )
    return res


class PoolGrowRequest(BaseModel):
    way: str = Field(..., min_length=1, max_length=32)
    to: str = Field(default="", max_length=256)
    drives: list[str] = Field(..., min_length=1, max_length=2)


@router.get("/pools/{pool_id}/grow", dependencies=[Depends(require_scope("storage:admin"))])
def get_pool_grow_plan(pool_id: PoolId) -> dict[str, Any]:
    """The ways the pool can take another drive, the empty drives, and copying that runs now."""
    try:
        return get_storage_platform().grow_plan(pool_id)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post(
    "/pools/{pool_id}/grow",
    dependencies=[Depends(require_scope("storage:admin")), Depends(require_confirmation("storage.pool.grow"))],
)
def grow_pool(
    pool_id: PoolId,
    req: PoolGrowRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Adds empty drives to the pool with its own tool. Nothing is erased: the drives must hold nothing."""
    try:
        res = get_storage_platform().grow_pool(pool_id, req.way, req.to, req.drives)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if not res.get("started"):
        raise HTTPException(status_code=409, detail=str(res.get("message") or "The drive could not be added."))
    from backend.users_db import log_security_event

    log_security_event(
        "storage.pool_grow",
        "success",
        actor_id=getattr(principal, "user_id", None),
        actor_username=principal.username,
        actor_ip=request.client.host if request.client else "",
        details={"pool": pool_id, "way": res.get("way", ""), "added": res.get("added", [])},
    )
    return res


class PoolEraseRequest(BaseModel):
    confirm_name: str = ""
    current_password: str = ""


def _erase_guard(pool_id: str, req: PoolEraseRequest, principal: AuthenticatedPrincipal) -> Any:
    """The typed name and the password, as for creating a pool; then the platform decides."""
    from backend.passwords import verify_password
    from backend.users_db import get_user_by_username

    if req.confirm_name != pool_id:
        raise HTTPException(status_code=400, detail="Type the pool's name to delete it.")
    user = get_user_by_username(principal.username)
    if not user or not verify_password(req.current_password or "", user.get("password_hash", "")):
        raise HTTPException(status_code=403, detail="Your password was not right.")
    return get_storage_platform()


@router.get("/pools/{pool_id}/erase-plan", dependencies=[Depends(require_scope("storage:admin"))])
def get_pool_erase_plan(pool_id: PoolId) -> dict[str, Any]:
    """Which drives "Delete pool and erase its drives" would erase, each confirmed on disk (S29)."""
    adapter = get_storage_platform()
    try:
        plan = adapter.erase_plan(pool_id)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    shares = [
        sh.name
        for sh in adapter.list_shares()
        if plan.get("mountpoint") and str(sh.mountpoint or "").startswith(plan["mountpoint"])
    ]
    return {**plan, "shares": shares}


@router.post(
    "/pools/{pool_id}/erase",
    dependencies=[Depends(require_scope("storage:admin")), Depends(require_confirmation("storage.pool.erase"))],
)
def erase_storage_pool(
    pool_id: PoolId, req: PoolEraseRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Deletes the pool and erases its drives: only drives its own tool lists and whose labels carry
    its id; one that cannot be confirmed refuses the whole erase (S29)."""
    adapter = _erase_guard(pool_id, req, principal)
    try:
        return adapter.erase_pool(pool_id)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post(
    "/pools/{pool_id}/export",
    dependencies=[Depends(require_scope("storage:admin"))],
)
def export_storage_pool(pool_id: PoolId, req: StoragePoolExportRequest = StoragePoolExportRequest()) -> dict[str, Any]:  # noqa: B008
    """
    Gracefully flushes dirty write cache, terminates active handles,
    and exports/unmounts a storage pool for safe physical detachment.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if not caps.can_export_pools:
        raise HTTPException(
            status_code=403,
            detail=f"Pool export is disabled on {adapter.get_platform_type().value} in Observer Mode.",
        )
    try:
        return adapter.export_pool(pool_id=pool_id, force=req.force)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logger.error(f"[StorageAPI] Error exporting pool '{one_line(pool_id)}': {one_line(e)}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/pools/{pool_id}/allow-changes",
    dependencies=[Depends(require_scope("storage:admin"))],
)
def allow_pool_changes(pool_id: PoolId) -> dict[str, Any]:
    """Opens for writing a pool that was imported read-only; it is then one of this system's pools."""
    adapter = get_storage_platform()
    allow = getattr(adapter, "allow_changes", None)
    if allow is None or adapter.get_capabilities().is_observer_mode:
        raise HTTPException(status_code=403, detail=f"Not available on {adapter.get_platform_type().value}.")
    try:
        return allow(pool_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get(
    "/pools/discover",
    dependencies=[Depends(require_scope("storage:admin", "storage:read"))],
)
def discover_external_storage_pools() -> dict[str, Any]:
    """
    Discovers unimported or detachable external storage pools (e.g. USB/Thunderbolt DAS).
    """
    if _in_container():
        return {"status": "ok", "discovered_pools": [], "available": False}
    adapter = get_storage_platform()
    try:
        discovered = adapter.discover_external_pools()
        return {"status": "ok", "discovered_pools": discovered, "available": True}
    except Exception as e:
        logger.warning(f"[StorageAPI] Error discovering external pools: {e}")
        return {"status": "ok", "discovered_pools": []}


@router.post(
    "/pools/import",
    dependencies=[Depends(require_scope("storage:admin"))],
)
def import_storage_pool(req: StoragePoolImportRequest) -> dict[str, Any]:
    """
    Imports an external storage pool into the platform.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if not caps.can_import_pools:
        raise HTTPException(
            status_code=403,
            detail=f"Pool import is disabled on {adapter.get_platform_type().value} in Observer Mode.",
        )
    more: dict[str, Any] = {k: v for k, v in (("guid", req.guid), ("force", req.force)) if v}
    try:
        done = adapter.import_pool(pool_id=req.pool_id, fs_type=req.fs_type, target_mount=req.target_mount, **more)
        from backend.services import moved_in

        moved_in.fit_if_pending()  # shares from another install that wait for this pool
        return done
    except PoolUsedElsewhere as e:
        raise ApiError(409, str(e), "pool_used_elsewhere", text=said("pool_used_elsewhere", pool=req.pool_id)) from e
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        logger.error(f"[StorageAPI] Error importing pool '{one_line(req.pool_id)}': {one_line(e)}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete(
    "/shares/{name}",
    dependencies=[Depends(require_scope("shares:manage")), Depends(require_confirmation("share.delete"))],
)
def delete_storage_share(name: str) -> dict[str, Any]:
    """
    Deletes a network share configuration. Forbidden in Observer Mode.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}.",
        )
    try:
        return adapter.delete_share(name=name)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.get("/pools/{pool_id}/snapshots", dependencies=[Depends(require_scope("storage:read", "storage:admin"))])
def list_storage_snapshots(pool_id: PoolId) -> list[dict[str, Any]]:
    """
    Lists filesystem subvolume snapshots for a storage pool.
    """
    adapter = get_storage_platform()
    return adapter.list_snapshots(pool_id=pool_id)


@router.post("/pools/{pool_id}/snapshots", dependencies=[Depends(require_scope("storage:admin"))])
def create_storage_snapshot(pool_id: PoolId, req: StorageSnapshotCreateRequest) -> dict[str, Any]:
    """
    Creates an atomic Btrfs subvolume snapshot. Forbidden in Observer Mode.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}.",
        )
    try:
        return adapter.create_snapshot(
            pool_id=pool_id,
            subvol_name=req.subvolume,
            snapshot_name=req.snapshot_name,
            readonly=req.readonly,
            worm_mode=req.worm_mode,
            retention_days=req.retention_days,
        )
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.delete(
    "/pools/{pool_id}/snapshots/{snapshot_name}",
    dependencies=[Depends(require_scope("storage:admin")), Depends(require_confirmation("storage.snapshot.delete"))],
)
def delete_storage_snapshot(pool_id: PoolId, snapshot_name: str) -> dict[str, Any]:
    """
    Deletes a Btrfs subvolume snapshot. Forbidden in Observer Mode or if WORM locked.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}.",
        )
    try:
        single_name(snapshot_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        res = adapter.delete_snapshot(pool_id=pool_id, snapshot_name=snapshot_name)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    if res.get("status") == "error":  # nothing was deleted, so this is not a 200
        raise HTTPException(status_code=409, detail=res.get("message") or "The snapshot could not be deleted.")
    return res


@router.post("/pools/{pool_id}/snapshots/break-glass-delete", dependencies=[Depends(require_scope("storage:admin"))])
def break_glass_delete_snapshot(pool_id: PoolId, req: StorageSnapshotBreakGlassDeleteRequest) -> dict[str, Any]:
    """
    Overrides Governance-mode WORM lock to delete a snapshot with mandatory audit logging.
    Forbidden for Compliance-mode WORM locks before retention expiry.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}.",
        )
    try:
        return adapter.delete_snapshot(
            pool_id=pool_id,
            snapshot_name=req.snapshot_name,
            break_glass=True,
            reason=req.reason,
        )
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


class SmartScheduleUpdateRequest(BaseModel):
    enabled: bool | None = None
    short_test_interval: str | None = None
    short_test_day: int | None = None
    short_test_hour: int | None = None
    extended_test_interval: str | None = None
    extended_test_day: int | None = None
    extended_test_hour: int | None = None
    skip_if_standby: bool | None = None


@router.get("/smart/schedule", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def get_smart_test_schedule() -> dict[str, Any]:
    """
    Returns current SMART test schedule, intervals, and last execution timestamps.
    """
    from backend.services.scheduler import get_smart_schedule

    return get_smart_schedule()


@router.post("/smart/schedule", dependencies=[Depends(require_scope("storage:admin"))])
def update_smart_test_schedule(req: SmartScheduleUpdateRequest) -> dict[str, Any]:
    """
    Configures automated Short and Extended SMART test schedules.
    Preserves skip_if_standby=True invariant to never spin up sleeping drives.
    """
    from backend.services.scheduler import save_smart_schedule

    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    return save_smart_schedule(payload)


@router.get("/damaged-files", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def get_damaged_files() -> dict[str, Any]:
    """The files the last check (scrub) found damaged, per pool, as ZFS names them. Empty when
    nothing is damaged or the pools cannot be read."""
    from backend.services import pool_alerts

    return {"pools": pool_alerts.damaged_files()}


@router.get("/smart/failure-predictions", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def get_smart_failure_predictions() -> list[dict[str, Any]]:
    """
    Scrutiny-style failure probability analytics and historical attribute velocity
    for all discovered storage drives.
    """
    from backend.db import query_smart_velocity
    from backend.hardware.disks import _discover_disks

    disks = _discover_disks()
    predictions = []
    for d in disks:
        dev_name = d.get("dev", "")
        if dev_name:
            v_data = query_smart_velocity(dev_name)
            v_data["model"] = d.get("model", "")
            v_data["serial"] = d.get("serial", "")
            v_data["type"] = d.get("type", "hdd")
            v_data["status"] = d.get("status", "OK")
            predictions.append(v_data)
    return predictions


@router.get("/unraid-api/status", dependencies=[Depends(require_scope("storage:read", "system:view"))])
async def unraid_api_status() -> dict[str, Any]:
    """Array, disks, shares and parity check from the Unraid API (the API link, D5)."""
    from backend.services import unraid_api

    if not unraid_api.configured():
        raise HTTPException(status_code=404, detail="Unraid API not configured (UNRAID_API_URL, UNRAID_API_KEY)")
    try:
        return await asyncio.to_thread(unraid_api.status)
    except unraid_api.UnraidApiError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# --- where a share's space goes (storage analyzer) --------------------------------------------


class AnalyzeIn(BaseModel):
    share: str = Field(..., min_length=1, max_length=128)


def _share_root(name: str) -> str | None:
    for share in get_storage_platform().list_shares():
        if share.name == name and share.mountpoint and os.path.isdir(share.mountpoint):
            return share.mountpoint
    return None


@router.post("/analysis", dependencies=[Depends(require_scope("storage:admin"))])
def start_storage_analysis(
    req: AnalyzeIn, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Starts adding up where a share's space goes (a job; it reads the share's folder listing)."""
    from backend.services import storage_analyzer

    root = _share_root(req.share)
    if not root:
        raise HTTPException(status_code=404, detail="No such share")
    try:
        job_id = storage_analyzer.start(req.share, root, owner=principal.username or None)
    except RuntimeError:
        raise HTTPException(status_code=409, detail="That share is being analysed already") from None
    return {"share": req.share, "job_id": job_id}


@router.get("/analysis/{share}", dependencies=[Depends(require_scope("storage:admin"))])
def get_storage_analysis(share: Annotated[str, Path(min_length=1, max_length=128)]) -> dict[str, Any]:
    """The last analysis of a share (none yet: result is null), and whether one is running."""
    from backend.services import storage_analyzer

    return {"share": share, "running": storage_analyzer.running(share), "result": storage_analyzer.last_result(share)}
