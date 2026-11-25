"""The host door (ADR 0006): a root service that changes the machine for Kiboto's web process.

It listens on a Unix socket (door.SOCK) and takes connections from root and the `kiboto` user
only (checked with SO_PEERCRED). Each request names one operation from OPERATIONS with its
arguments; anything else is refused: an unknown operation, a missing, extra or wrongly typed
argument. There is no shell and no free-form command: each operation is a function of Kiboto's
own that checks what it is given, as the API does. Every call is written to door-audit.log in
the data folder.

Run by kiboto-door.service on a machine Kiboto runs: `python -m backend.services.host_door`.
Until the web process gives up root (ADR 0006, the last step) it is used where it runs, and the
callers do the work themselves where it does not."""

from __future__ import annotations

import grp
import json
import os
import pwd
import re
import socket
import stat
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend import door
from backend.config import DATA_DIR, logger
from backend.hardware.pal.base import PlatformCapabilityError, PoolUsedElsewhere

AUDIT = os.path.join(DATA_DIR, "door-audit.log")
MAX_REQUEST = 64 * 1024
USER = "kiboto"  # the user the web process will run as


@dataclass(frozen=True)
class Operation:
    run: Callable[..., Any]
    args: dict[str, tuple[type, ...]]  # every argument, required, with the types it may have
    max_len: int = 256  # for text arguments


def _host(name: str) -> Callable[..., Any]:
    def run(**kw: Any) -> Any:
        from backend.services import host_basics

        return getattr(host_basics, name)(**kw)

    return run


def _net(name: str) -> Callable[..., Any]:
    def run(**kw: Any) -> Any:
        from backend.hardware.net import managed

        return getattr(managed, name)(**kw)

    return run


def _samba(name: str) -> Callable[..., Any]:
    """samba_host's own function, after the account numbers are checked to be Kiboto's: a number
    below its range (0 is root) would make a system account of someone."""

    def run(**kw: Any) -> Any:
        from backend.services import samba_host, smb_accounts

        numbers = list((kw.get("numbers") or {}).values()) + ([kw["number"]] if "number" in kw else [])
        for n in numbers:
            if type(n) is not int or not smb_accounts.FIRST_UID <= n < LAST_UID:
                raise ValueError("account numbers come from Kiboto's own range")
        return getattr(samba_host, name)(**kw)

    return run


def _samba_point_here() -> bool:
    from backend.services import samba_host
    from backend.services.samba_engine import SAMBA_CONF_FILE

    return samba_host.point_samba_here(SAMBA_CONF_FILE)  # the door's own path, not one it was sent


def _nfs_apply() -> bool:
    from backend.services import nfs_engine

    return nfs_engine.NfsEngine().apply_exports(inside_storage_only=True)  # the saved rules, read again


def _storage(name: str, check: Callable[[dict[str, Any]], None] | None = None) -> Callable[..., Any]:
    """The storage adapter's own method, for a pool named by its name (pool_rules), after `check`
    has looked at the rest. The adapter keeps every snapshot and subvolume name to one folder
    name (fsutil.child_path) and the pool's folder to its storage roots (get_pool_path)."""

    def run(**kw: Any) -> Any:
        from backend.hardware.pal import pool_rules
        from backend.hardware.pal_storage import get_storage_platform

        if "pool_id" in kw:
            pool_rules.pool_id(kw["pool_id"])
        if check is not None:
            check(kw)
        return getattr(get_storage_platform(), name)(**kw)

    return run


def _new_pool(kw: dict[str, Any]) -> None:
    """A new pool: its name and kind, a mount point inside the pool root, and drives that are
    whole, unmounted and in no pool or array (disk_safety). Whether a drive's old data may be
    erased is the person's answer, asked by the page with their password; the door still never
    formats a drive that is in use, the system disk among them."""
    from backend.hardware.disk_safety import check_disks
    from backend.hardware.pal import pool_rules
    from backend.hardware.pal_storage import get_storage_platform

    pool_rules.new_pool_name(kw["name"])
    if kw["fs_type"].lower() not in pool_rules.KINDS_MADE or not re.match(r"^[A-Za-z0-9]{1,16}$", kw["profile"]):
        raise ValueError("Kiboto makes ZFS, btrfs and ext4 pools.")
    kw["mountpoint"] = pool_rules.new_pool_mount(kw["mountpoint"])
    disks = kw["disks"]
    if not disks or len(disks) > 64 or not all(type(d) is str and 0 < len(d) <= 256 for d in disks):
        raise ValueError("disks: one to 64 drive names")
    resolve = getattr(get_storage_platform(), "_resolve_disk_path", None)
    problems = check_disks([resolve(d) if resolve else d for d in disks], allow_erase=True)
    if problems:
        raise ValueError(
            "These disks can't be formatted: " + "; ".join(f"{p['disk']}: {p['reason']}" for p in problems)
        )


def _imported(kw: dict[str, Any]) -> None:
    from backend.hardware.pal import pool_rules

    pool_rules.pool_name(kw["pool_id"])
    if not re.match(r"^[a-z0-9]{1,16}$", kw["fs_type"]) or not re.match(r"^[0-9]{0,24}$", kw["guid"]):
        raise ValueError("fs_type and guid are as the pool list shows them")
    kw["target_mount"] = pool_rules.import_mount(kw["target_mount"])


def _share_folder(kw: dict[str, Any]) -> None:
    """A shared folder's folder: inside the storage roots and not Kiboto's own data folder
    (validate_share_path), not on the system disk of a machine Kiboto runs, with a size limit
    that is a number of bytes."""
    from backend.hardware.pal_storage import get_storage_platform
    from backend.services.samba_engine import validate_share_path

    path = validate_share_path(kw["path"])
    off_system = getattr(get_storage_platform(), "_not_on_the_system_disk", None)
    kw["path"] = off_system(path) if off_system else path
    if not 0 <= kw["quota_bytes"] < 1 << 60:
        raise ValueError("quota_bytes must be a size in bytes")


def _self_test(dev_name: str, action: str) -> tuple[int, str, str]:
    """A self-test of a drive: the name must be a block device's (sda, nvme0n1), not a path."""
    import stat

    from backend.hardware import disks

    if not re.match(r"^[a-z][a-z0-9]{1,15}$", dev_name):
        raise ValueError("dev_name must be a drive's name")
    real = os.path.realpath(disks._resolve_dev_path(dev_name))
    try:
        is_block = stat.S_ISBLK(os.stat(real).st_mode)
    except OSError:
        is_block = False
    if not is_block:
        raise ValueError(f"{dev_name} is not a drive here")
    return disks.self_test(dev_name, action)


def _sleep_after(minutes: int) -> list[dict[str, Any]]:
    from backend.hardware import drive_sleep

    return drive_sleep.apply(minutes)


def _update_start(image: str, version: str) -> str:
    """An update, after the door's own check of the image's signature; the data folder and port
    are the door's."""
    from backend import config
    from backend.services import image_signature, native_update

    if version and not re.match(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,39}$", version):
        raise ValueError("version must be a version's name")
    image_signature.install_allowed(image)
    return native_update.start(image, version, config.DATA_DIR, config.PORT)


def _update_back(snapshot_id: str) -> None:
    from backend import config
    from backend.services import native_update

    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$", snapshot_id):
        raise ValueError("snapshot_id must be a saved version's id")
    native_update.start_back(snapshot_id, config.DATA_DIR, config.PORT)


def _usb(name: str) -> Callable[..., Any]:
    """usb_mount's own: it opens only a USB disk it lists itself, and ejects only a folder of
    /mnt/disks with a disk mounted on it."""

    def run(**kw: Any) -> Any:
        from backend.hardware import usb_mount

        return getattr(usb_mount, name)(**kw)

    return run


def _home(username: str, quota_bytes: int, only_limit: bool = False) -> dict[str, Any]:
    from backend.services import user_spaces

    return user_spaces.home_in_door(username, quota_bytes, only_limit)


def _crypt_mount(cipher: str, plain: str, password: str, read_only: bool) -> bool:
    from backend.services import encrypted_folders

    return encrypted_folders.mount_in_door(cipher, plain, password, read_only)


def _crypt_unmount(path: str) -> bool:
    from backend.services import encrypted_folders

    return encrypted_folders.unmount_in_door(path)


def _pools_bring_back() -> dict[str, str]:
    from backend.services import pools_at_boot

    return pools_at_boot.bring_back()


def _restart_kiboto(delay: int) -> bool:
    from backend.services import host_basics

    return host_basics.restart_here(delay)


def _pools_look() -> list[dict[str, Any]]:
    from backend.services import pool_copy

    return pool_copy.look_in_door(USER)


def _card(device: str, offset: int) -> str:
    from backend.services import copy_engine

    return copy_engine.card_in_door(device, offset)


def _uncard() -> bool:
    from backend.services import copy_engine

    return copy_engine.uncard_in_door()


def _cloud_mount(name: str, remote_path: str, vfs_cache: str, read_only: bool) -> dict[str, Any]:
    """A cloud drive of Kiboto's own list as a folder under /mnt/remotes (rclone mount)."""
    from backend.services import rclone_engine

    rclone_engine.check_remote_name(name)
    if vfs_cache not in rclone_engine.VFS_CACHE_MODES or remote_path.startswith("-") or "\n" in remote_path:
        raise ValueError("a cache mode rclone knows, and a path in the drive")
    return rclone_engine.get_rclone_engine().mount_remote(name, remote_path, vfs_cache, read_only)


def _cloud_unmount(name: str) -> dict[str, Any]:
    from backend.services import rclone_engine

    return rclone_engine.get_rclone_engine().unmount_remote(name)


def _power(action: str) -> dict[str, Any]:
    from backend.services import host_power

    if action not in ("reboot", "shutdown"):
        raise ValueError("action is reboot or shutdown")
    return host_power.run(action)  # the door's own list of commands, never one it was sent


def _names() -> dict[str, Any]:
    from backend.services import nas_name

    return nas_name.ensure()  # from the saved setting; nothing the caller sent


def _apps_hosts() -> bool:
    from backend.services import app_hosts

    return app_hosts.sync()  # the block from Docker's own list; nothing the caller sent


def _firstrun(name: str) -> Callable[[], Any]:
    """The first-time code's notice on the machine's screen and SSH greeting: written from the code
    file the door reads itself, or removed. No argument: nothing else can be put in /etc."""

    def run() -> Any:
        from backend import first_run

        return first_run.refresh_here() if name == "notice" else first_run.clear_here()

    return run


def _packages(name: str) -> Callable[[], Any]:
    def run() -> Any:
        from backend.services import host_set, native_update

        if name == "add_missing":
            return native_update.add_missing_tools(os.path.join(native_update.PREFIX, "current"))
        return host_set.check() if name == "check" else host_set.start()

    return run


def _key(name: str) -> Callable[..., Any]:
    """machine_key's own function: the data key's folder (/etc/kiboto/keys) and the security chip
    are root's. "keys.text" hands the key to the web process, which encrypts with it."""

    def run(**kw: Any) -> Any:
        from backend import machine_key

        if not machine_key.active():
            raise ValueError("this machine keeps no data key of its own")
        return getattr(machine_key, name)(**kw)

    return run


def _fan_file(path: str, value: int) -> bool:
    """A fan's speed or mode: only a pwm file of a hwmon device, with a value such a file takes."""
    from backend.config import HOST_SYS
    from backend.hardware import fans

    base = re.escape((HOST_SYS or "/sys").rstrip("/"))
    if not re.fullmatch(base + r"/class/hwmon/hwmon\d{1,3}/pwm\d{1,2}(_enable)?", path) or not 0 <= value <= 255:
        raise ValueError("only a fan's pwm file, with a value from 0 to 255")
    return bool(fans._write_sysfs(path, value))


def _fan_register(channel: int, pwm_val: int) -> bool:
    """A fan of the embedded controller on the boards that have one (fans.ZettlabMmioFanController)."""
    from backend.hardware import fans

    if channel not in (1, 2, 3) or not 0 <= pwm_val <= 255:
        raise ValueError("channel 1 to 3, a value from 0 to 255")
    mmio = fans.get_mmio_fan_controller()
    if mmio is None:
        raise ValueError("this machine has no such fan controller")
    return bool(mmio.write_pwm(channel, pwm_val))


def _in_storage(path: str, *, leaf: bool = True) -> str:
    """`path` when it is inside the storage folders and not Kiboto's own (validate_share_path); for
    a `leaf` its folder is checked, so a link at the end is not followed (owners are set with
    lchown)."""
    from backend.services.samba_engine import validate_share_path

    if not os.path.isabs(path or "") or "\x00" in path:
        raise ValueError("an absolute path inside the storage folders")
    validate_share_path(os.path.dirname(path) if leaf else path)
    return path


def _no_root(*ids: int) -> None:
    if any(type(i) is not int or i <= 0 for i in ids):
        raise ValueError("files go to a person or the file server, never to root")


def _files(name: str) -> Callable[..., Any]:
    """owned.py's own function for files and folders in the storage folders (ADR 0006 step 8): the
    door hands what the web process made to the folder's people."""

    def run(**kw: Any) -> Any:
        from backend import owned
        from backend.fsutil import prune_protected

        for key in ("path", "dst", "src"):
            if key in kw:
                _in_storage(kw[key])
        for key in ("folder", "top"):
            if key in kw:
                _in_storage(kw[key], leaf=False)
        if name == "to_people":
            _no_root(*owned._ids(kw["user"], kw["group"]))
        if name in ("to_people", "to_person") and kw["mode"] & ~0o777:
            raise ValueError("a folder's rights, without set-id bits")
        if name == "to_person":
            from backend.services import smb_accounts

            if not smb_accounts.FIRST_UID <= kw["uid"] < LAST_UID:
                raise ValueError("account numbers come from Kiboto's own range")
            _no_root(kw["gid"])
        if name == "hand_back":
            _no_root(kw["uid"], kw["gid"])
            return owned._hand(kw["path"], kw["uid"], kw["gid"])
        if name == "give_back":
            return owned.give_back(kw["top"], prune_protected)
        return getattr(owned, name)(**kw)

    return run


def _smartctl(args: list[Any], limit: float) -> dict[str, Any]:
    from backend.hardware import smart_read

    return smart_read.read_in_door(args, limit)


_TAP = re.compile(r"kbt[0-9a-f]{8}")


def _vm_tap(name: str, bridge: str) -> bool:
    """A virtual machine's tap device on a bridge, owned by the web user (vm_qemu.tap_name): only a
    name of that form, only on a bridge that is there."""
    from backend.proc import run_bounded

    if not _TAP.fullmatch(name) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", bridge):
        raise ValueError("a machine's tap device on a bridge")
    if not os.path.isdir(f"/sys/class/net/{bridge}/bridge"):
        raise ValueError(f"{bridge} is not a bridge here")
    steps = (
        []
        if os.path.exists(f"/sys/class/net/{name}")
        else [["tuntap", "add", "dev", name, "mode", "tap", "user", USER]]
    )
    steps += [["link", "set", "dev", name, "master", bridge], ["link", "set", "dev", name, "up"]]
    for step in steps:
        r = run_bounded(["ip", *step], timeout=15, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"ip {' '.join(step[:2])}: {(r.stderr or '').strip()[-200:]}")
    return True


def _vm_tap_remove(name: str) -> bool:
    from backend.proc import run_bounded

    if not _TAP.fullmatch(name):
        raise ValueError("a machine's tap device")
    if os.path.exists(f"/sys/class/net/{name}"):
        run_bounded(["ip", "link", "del", "dev", name], timeout=15, capture_output=True, text=True)
    return True


def _renamed(kw: dict[str, Any]) -> None:
    from backend.hardware.pal import pool_rules

    pool_rules.pool_name(kw["new_name"])


def _firewall_apply(st: dict[str, Any]) -> None:
    from backend.services import firewall

    firewall.apply(firewall.cleaned(st))  # only the settings the page offers, whatever was sent


LOADED = door.version()  # the code this door started with; Kiboto compares the files of now with it
TEXT, ON, MAYBE_TEXT, MAP, NUMBER, LIST = (str,), (bool,), (str, type(None)), (dict,), (int,), (list,)
LAST_UID = 60000  # Kiboto's account numbers: smb_accounts.FIRST_UID up to here
OPERATIONS: dict[str, Operation] = {
    "door.ping": Operation(lambda: "pong", {}),
    "door.version": Operation(lambda: LOADED, {}),
    "host.set_name": Operation(_host("set_host_name"), {"name": TEXT}, max_len=63),
    "host.set_time_zone": Operation(_host("set_time_zone"), {"zone": TEXT}, max_len=64),
    "host.set_clock_automatic": Operation(_host("set_clock_automatic"), {"on": ON}),
    "host.set_ssh": Operation(_host("set_ssh"), {"on": ON}),
    # the network's settings, each tried with the machine's own way back (hardware/net/managed.py,
    # which checks every value); the trial's state is in the data folder, where the page reads it
    "network.try_address": Operation(_net("start_trial"), {"changes": MAP}),
    "network.try_bridge": Operation(_net("start_bridge_trial"), {"on": ON, "port": TEXT, "now": MAP}, max_len=32),
    "network.keep": Operation(_net("keep"), {"key": MAYBE_TEXT}, max_len=128),
    "network.go_back": Operation(_net("go_back"), {"key": MAYBE_TEXT}, max_len=128),
    "network.settle": Operation(_net("settle"), {}),
    "network.trial_status": Operation(_net("trial_status"), {}),
    "network.ensure_fallback": Operation(_net("ensure_fallback"), {}),
    "firewall.apply": Operation(_firewall_apply, {"st": MAP}),
    # accounts and file servers (samba_host checks the names; the door checks the numbers)
    "samba.point_here": Operation(_samba_point_here, {}),
    "samba.reload": Operation(_samba("reload"), {"changed": (dict, type(None)), "numbers": MAP}),
    "samba.set_password": Operation(
        _samba("set_password"), {"name": TEXT, "number": NUMBER, "password": TEXT}, max_len=128
    ),
    "samba.remove": Operation(_samba("remove"), {"name": TEXT}, max_len=64),
    "samba.set_enabled": Operation(_samba("set_enabled"), {"name": TEXT, "enabled": ON}, max_len=64),
    "nfs.apply": Operation(_nfs_apply, {}),
    # storage (ADR 0006 step 4)
    "storage.create_snapshot": Operation(
        _storage("create_snapshot"),
        {
            "pool_id": TEXT,
            "subvol_name": TEXT,
            "snapshot_name": TEXT,
            "readonly": ON,
            "worm_mode": MAYBE_TEXT,
            "retention_days": (int, type(None)),
        },
        max_len=128,
    ),
    "storage.delete_snapshot": Operation(
        _storage("delete_snapshot"),
        {"pool_id": TEXT, "snapshot_name": TEXT, "break_glass": ON, "reason": TEXT},
        max_len=512,
    ),
    "storage.scrub": Operation(_storage("trigger_scrub"), {"pool_id": TEXT, "action": TEXT}, max_len=128),
    "storage.create_pool": Operation(
        _storage("create_pool", _new_pool),
        {"name": TEXT, "fs_type": TEXT, "profile": TEXT, "disks": LIST, "mountpoint": TEXT},
        max_len=256,
    ),
    "storage.import_pool": Operation(
        _storage("import_pool", _imported),
        {"pool_id": TEXT, "fs_type": TEXT, "target_mount": MAYBE_TEXT, "force": ON, "guid": TEXT},
        max_len=256,
    ),
    "storage.rename_pool": Operation(
        _storage("rename_pool", _renamed), {"pool_id": TEXT, "new_name": TEXT}, max_len=128
    ),
    "storage.export_pool": Operation(_storage("export_pool"), {"pool_id": TEXT, "force": ON}, max_len=128),
    "storage.destroy_pool": Operation(_storage("destroy_pool"), {"pool_id": TEXT}, max_len=128),
    "storage.erase_pool": Operation(_storage("erase_pool"), {"pool_id": TEXT}, max_len=128),
    "storage.allow_changes": Operation(_storage("allow_changes"), {"pool_id": TEXT}, max_len=128),
    # the data key (ADR 0006 step 6)
    "keys.text": Operation(_key("key_text"), {}),
    "keys.wanted": Operation(_key("wanted"), {}),
    "keys.ensure": Operation(_key("ensure"), {}),
    "keys.status": Operation(_key("status"), {}),
    "keys.to_write_down": Operation(_key("recovery_key_to_write_down"), {}),
    "keys.written_down": Operation(_key("written_down"), {}),
    "keys.unlock": Operation(_key("unlock"), {"typed": TEXT}, max_len=64),
    "keys.adopt": Operation(_key("adopt"), {"data_key": TEXT, "box": MAP}, max_len=128),
    "keys.renew": Operation(_key("renew_recovery_key"), {}),
    "keys.wrapped": Operation(_key("wrapped_text"), {}),
    # people's files (ADR 0006 step 8)
    "files.like_folder": Operation(_files("like_folder"), {"path": TEXT}, max_len=4096),
    "files.rights_again": Operation(_files("rights_again"), {"path": TEXT}, max_len=4096),
    "files.like_source": Operation(_files("like_source"), {"src": TEXT, "dst": TEXT}, max_len=4096),
    "files.hand_back": Operation(_files("hand_back"), {"path": TEXT, "uid": NUMBER, "gid": NUMBER}, max_len=4096),
    "files.give_back": Operation(_files("give_back"), {"top": TEXT}, max_len=4096),
    "files.to_people": Operation(
        _files("to_people"), {"folder": TEXT, "user": TEXT, "group": TEXT, "mode": NUMBER}, max_len=4096
    ),
    "files.to_person": Operation(
        _files("to_person"), {"folder": TEXT, "uid": NUMBER, "gid": NUMBER, "mode": NUMBER}, max_len=4096
    ),
    # fans (ADR 0006 step 6)
    "fans.sysfs": Operation(_fan_file, {"path": TEXT, "value": NUMBER}, max_len=128),
    "fans.ec_pwm": Operation(_fan_register, {"channel": NUMBER, "pwm_val": NUMBER}),
    # updates and packages (ADR 0006 step 5)
    "update.start": Operation(_update_start, {"image": TEXT, "version": TEXT}, max_len=320),
    "update.back": Operation(_update_back, {"snapshot_id": TEXT}, max_len=128),
    "packages.add_missing": Operation(_packages("add_missing"), {}),
    "hosts.apps": Operation(_apps_hosts, {}),
    "names.ensure": Operation(_names, {}),
    "power.run": Operation(_power, {"action": TEXT}, max_len=16),
    "cloud.mount": Operation(
        _cloud_mount, {"name": TEXT, "remote_path": TEXT, "vfs_cache": TEXT, "read_only": ON}, max_len=1024
    ),
    "cloud.unmount": Operation(_cloud_unmount, {"name": TEXT}, max_len=128),
    "copy.mount": Operation(_card, {"device": TEXT, "offset": (int,)}, max_len=128),
    "copy.unmount": Operation(_uncard, {}),
    "pools.look": Operation(_pools_look, {}),
    "pools.bring_back": Operation(_pools_bring_back, {}),
    "kiboto.restart": Operation(_restart_kiboto, {"delay": (int,)}),
    "crypt.mount": Operation(
        _crypt_mount, {"cipher": TEXT, "plain": TEXT, "password": TEXT, "read_only": ON}, max_len=4096
    ),
    "crypt.unmount": Operation(_crypt_unmount, {"path": TEXT}, max_len=4096),
    "files.home": Operation(_home, {"username": TEXT, "quota_bytes": NUMBER, "only_limit": ON}, max_len=64),
    "usb.open": Operation(_usb("open_disk"), {"device": TEXT}, max_len=128),
    "usb.eject": Operation(_usb("eject"), {"path": TEXT}, max_len=4096),
    "vm.tap": Operation(_vm_tap, {"name": TEXT, "bridge": TEXT}, max_len=32),
    "vm.tap_remove": Operation(_vm_tap_remove, {"name": TEXT}, max_len=32),
    "firstrun.notice": Operation(_firstrun("notice"), {}),
    "firstrun.clear": Operation(_firstrun("clear"), {}),
    "packages.check": Operation(_packages("check"), {}),
    "packages.host_set": Operation(_packages("host_set"), {}),
    "disks.smartctl": Operation(_smartctl, {"args": LIST, "limit": (int, float)}, max_len=64),
    "smart.self_test": Operation(_self_test, {"dev_name": TEXT, "action": TEXT}, max_len=32),
    "drives.sleep_after": Operation(_sleep_after, {"minutes": NUMBER}),
    "storage.share_folder": Operation(
        _storage("make_share_folder", _share_folder), {"path": TEXT, "quota_bytes": NUMBER}, max_len=4096
    ),
}


def _checked(request: Any) -> tuple[Operation, dict[str, Any]]:
    """The operation and its arguments, or ValueError saying what is wrong with the request."""
    if not isinstance(request, dict) or not isinstance(request.get("op"), str):
        raise ValueError("not a request")
    op = OPERATIONS.get(request["op"])
    if op is None:
        raise ValueError(f"no such operation: {request['op'][:60]}")
    args = request.get("args") or {}
    if not isinstance(args, dict) or set(args) != set(op.args):
        raise ValueError(f"{request['op']} takes {', '.join(sorted(op.args)) or 'nothing'}")
    for name, kinds in op.args.items():
        value = args[name]
        if type(value) not in kinds:  # bool is not int, int is not bool
            raise ValueError(f"{name} must be {' or '.join(k.__name__ for k in kinds)}")
        if type(value) is str and (len(value) > op.max_len or "\x00" in value):
            raise ValueError(f"{name} is too long")
    return op, args


def handle(request: Any, uid: int) -> dict[str, Any]:
    """One request from a caller with this uid, answered as {"ok", "result"} or {"ok", "error"}."""
    name = str(request.get("op"))[:60] if isinstance(request, dict) else "?"
    try:
        op, args = _checked(request)
    except ValueError as e:
        _audit(uid, name, "refused", str(e))
        return {"ok": False, "error": str(e)}
    try:
        result = op.run(**args)
    except (OSError, ValueError, RuntimeError, TypeError, LookupError, PlatformCapabilityError) as e:  # told
        logger.warning("[Door] %s failed: %s", name, e)
        _audit(uid, name, "failed", str(e))
        kind = _kind(e)
        return {"ok": False, "error": str(e), "kind": kind, "text": getattr(e, "text", None)}
    _audit(uid, name, "done", "")
    return {"ok": True, "result": result}


def _kind(e: Exception) -> str:
    """What the caller raises again on its side (door.DoorError.as_error, and the storage
    adapter's own kinds in generic_linux._through_door)."""
    if isinstance(e, ValueError):
        return "value"
    if isinstance(e, PoolUsedElsewhere):
        return "used_elsewhere"
    if isinstance(e, LookupError):
        return "lookup"
    if isinstance(e, RuntimeError):
        return "runtime"
    return "capability" if isinstance(e, PlatformCapabilityError) else "other"


def _audit(uid: int, op: str, outcome: str, why: str) -> None:
    line = json.dumps({"at": round(time.time()), "uid": uid, "op": op, "outcome": outcome, "why": why[:200]})
    try:
        with os.fdopen(_audit_file(AUDIT), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        logger.warning("[Door] the audit line was not written: %s", e)


def _audit_file(path: str) -> int:
    """The log, opened for appending. It is in the data folder, which the web process owns: a link
    put in its place, or a file that is not root's own, is moved aside and a new log begun, so root
    never writes through a link or into a file someone else chose."""
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    for attempt in (0, 1):
        try:
            fd = os.open(path, flags, 0o644)
        except OSError:
            if attempt:
                raise
            os.unlink(path)  # a link: taken away (the name, not what it points at)
            continue
        st = os.fstat(fd)
        if st.st_uid == os.geteuid() and st.st_nlink == 1 and stat.S_ISREG(st.st_mode):
            return fd
        os.close(fd)
        if attempt:
            raise OSError(f"{path} is not a file of this service's own")
        os.unlink(path)
    raise OSError(f"{path} could not be opened")


def allowed_uids() -> set[int]:
    """Root, and the user the web process runs as once it has one."""
    uids = {0}
    try:
        uids.add(pwd.getpwnam(USER).pw_uid)
    except KeyError:
        logger.debug("[Door] no %s user yet: root only", USER)
    return uids


def peer_uid(conn: socket.socket) -> int:
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", creds)
    return uid


def _serve_one(conn: socket.socket, uids: set[int]) -> None:
    with conn:
        uid = peer_uid(conn)
        if uid not in uids:
            uids = allowed_uids()  # the web user may have been made since the door started
        if uid not in uids:
            _audit(uid, "?", "refused", "not an allowed user")
            conn.sendall(b'{"ok": false, "error": "not allowed"}\n')
            return
        conn.settimeout(30)
        data = b""
        while not data.endswith(b"\n") and len(data) <= MAX_REQUEST:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        try:
            request = json.loads(data) if len(data) <= MAX_REQUEST else None
        except ValueError:
            request = None
        conn.sendall(json.dumps(handle(request, uid), default=str).encode() + b"\n")


def listen(path: str = door.SOCK) -> socket.socket:
    """The listening socket: only its owner and the web process's group may connect."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    try:
        os.chown(path, 0, grp.getgrnam(USER).gr_gid)
    except (KeyError, PermissionError):
        logger.debug("[Door] the socket stays root's alone")
    os.chmod(path, 0o660)
    server.listen(16)
    return server


def serve(path: str = door.SOCK, rounds: int | None = None) -> None:
    """Answers requests until stopped; `rounds` ends it after that many connections (tests)."""
    server = listen(path)
    uids = allowed_uids()
    logger.info("[Door] open on %s for uids %s", path, sorted(uids))
    with server:
        while rounds is None or rounds > 0:
            conn, _ = server.accept()
            threading.Thread(target=_serve_one, args=(conn, uids), daemon=True).start()
            rounds = None if rounds is None else rounds - 1


def _give_to_web_group(path: str, wait: float = 5.0) -> bool:
    """The proxy's socket, once it is there, in the web user's group: it may connect, others not."""
    end = time.monotonic() + wait
    while not os.path.exists(path):
        if time.monotonic() >= end:
            return False
        time.sleep(0.1)
    try:
        os.chown(path, -1, grp.getgrnam(USER).gr_gid)
    except (KeyError, OSError):  # no such user yet: root alone, which the web process still is
        return False
    return True


def keep_docker_proxy(path: str = door.DOCKER_SOCK, rounds: int | None = None) -> None:
    """Runs the Docker allow-list proxy (backend.docker_proxy) as a child of the door, started again
    when it stops (ADR 0006 step 7): the Docker socket is root's, so the proxy is too. Its socket is
    in the door's own run folder, which a restart of Kiboto does not remove; the web process's
    group may use it."""
    import subprocess
    import sys

    env = {**os.environ, "KIBOTO_DOCKER_PROXY_SOCK": path}
    wait = 1.0
    while rounds is None or rounds > 0:
        started = time.monotonic()
        proc = subprocess.Popen([sys.executable, "-m", "backend.docker_proxy"], env=env)
        _give_to_web_group(path)
        code = proc.wait()  # runs until stopped
        logger.warning("[Door] the Docker proxy stopped (%s); starting it again", code)
        wait = 1.0 if time.monotonic() - started > 60 else min(wait * 2, 30.0)
        time.sleep(wait)
        rounds = None if rounds is None else rounds - 1


def main() -> int:
    os.environ[door.IN_DOOR] = "1"  # an operation run here does not ask the door again
    from backend.config import RAW_DOCKER_SOCK

    if os.path.exists(RAW_DOCKER_SOCK):
        threading.Thread(target=keep_docker_proxy, name="DockerProxy", daemon=True).start()
    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
