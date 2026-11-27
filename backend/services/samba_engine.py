"""
Kiboto - Samba Engine
Manages production-grade Samba (SMB/CIFS) file sharing for Generic Linux & Turnkey Sidecars.
Features Apple vfs_fruit extensions for native macOS Finder & Time Machine support,
10GbE Multi-Channel performance tuning, and cross-platform permissions mapping.
"""

import configparser
import json
import os
import re
import socket
import sqlite3
import subprocess
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend import legacy_names, owned
from backend import settings as _settings
from backend.config import DATA_DIR, POOL_PATH, docker_sock, logger
from backend.config import docker_sock as _docker_sock_path
from backend.errors import SaidError
from backend.fsutil import atomic_write_json, atomic_write_text, json_locked, read_json
from backend.ignored_errors import ignored
from backend.services import samba_host

SAMBA_DIR = os.path.join(DATA_DIR, "samba")
SAMBA_CONF_FILE = os.path.join(SAMBA_DIR, "smb.conf")
PASSDB_FILE = os.path.join(SAMBA_DIR, "private", "passdb.tdb")  # Samba's own list of accounts
PASSDB_SEEN_FILE = os.path.join(SAMBA_DIR, "passdb.seen")  # which file that was at the last reload
SAMBA_SHARES_FILE = os.path.join(SAMBA_DIR, "shares.json")


def _snapshot_dir_for(share_path: str) -> str | None:
    """The pool's snapshot folder for a share at <pool>/@shares/<name> or <pool>/<name>."""
    import os

    parent = os.path.dirname(share_path.rstrip("/"))
    pool = os.path.dirname(parent) if os.path.basename(parent) == "@shares" else parent
    snapdir = os.path.join(pool, "@snapshots")
    return snapdir if pool else None


class SambaShareConfig(BaseModel):
    name: str
    path: str
    comment: str = ""
    read_only: bool = False
    guest_ok: bool = False  # guests only when asked for (SEC-06)
    browseable: bool = True
    timemachine: bool = False
    timemachine_quota_gb: int | None = None
    quota_gb: int | None = None
    force_user: str = "nobody"
    force_group: str = "users"
    valid_users: str | None = None
    read_list: str | None = None
    write_list: str | None = None
    previous_versions: bool = False  # Windows Previous Versions from scheduled snapshots
    recycle_bin: bool = True  # what is deleted over SMB goes to the share's Recycle Bin (REL-15)


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_PRINCIPAL = re.compile(r"^[@+&]{0,2}[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")
_UNIX_NAME = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}$", re.IGNORECASE)
_FORBIDDEN_PREFIXES = (
    "/etc",
    "/root",
    "/app",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
    "/host",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
)
FORBIDDEN_PREFIXES = _FORBIDDEN_PREFIXES  # system folders no share or app data may be in


def _allowed_share_roots() -> list[str]:
    from backend import config

    roots = [getattr(config, "POOL_PATH", "") or ""]
    roots += list(getattr(config, "ALLOWED_BROWSE_ROOTS", []) or [])
    return [os.path.realpath(r) for r in roots if r]


def validate_share_path(path: str) -> str:
    """The real path of a share folder, which must be inside the storage roots (SEC-06)."""
    path = (path or "").strip()
    if not os.path.isabs(path) or _CONTROL_CHARS.search(path):
        raise ValueError("Share path must be an absolute path")
    real = os.path.realpath(path)
    roots = _allowed_share_roots()
    system_path = real == "/" or any(real == f or real.startswith(f + "/") for f in _FORBIDDEN_PREFIXES)
    if not system_path:
        from backend.fsutil import is_protected

        for root in roots:
            if real == root:
                found = root  # the storage root itself
            elif real.startswith(root.rstrip("/") + "/"):
                found = real  # inside it: a prefix test on the resolved path, which code scanners read as a guard
            else:
                continue
            if is_protected(found):
                raise SaidError("Share path is Kiboto's own data folder; choose another folder", "share_kiboto_folder")
            return found
    places = ", ".join(roots) or "the storage pool"
    raise SaidError(f"Share path must be inside {places}", "share_outside", places=places)


def protected_veto_names(share_path: str) -> list[str]:
    """Names of app folders inside a share, for Samba's veto files (SEC-28): they never show over SMB."""
    from backend.fsutil import protected_dirs

    base = os.path.realpath(share_path or "")
    inside = [d for d in protected_dirs() if base and d != base and d.startswith(base.rstrip("/") + "/")]
    names = []
    for d in inside:
        if any(p != d and d.startswith(p.rstrip("/") + "/") for p in inside):
            continue  # its parent is hidden already (the install folder hides its data folder)
        name = os.path.basename(d)
        if name and name not in names and "/" not in name:
            names.append(name)
    return names


def validate_share(share: "SambaShareConfig") -> None:
    """Rejects settings that would let a share expose system paths or inject smb.conf lines (SEC-06)."""
    for field in ("name", "path", "comment", "force_user", "force_group", "valid_users", "read_list", "write_list"):
        value = getattr(share, field) or ""
        if _CONTROL_CHARS.search(value):
            raise ValueError(f"'{field}' must not contain line breaks or control characters")
    if "[" in share.comment or "]" in share.comment:
        raise ValueError("'comment' must not contain square brackets")

    share.path = validate_share_path(share.path)

    for field in ("valid_users", "read_list", "write_list"):
        value = getattr(share, field)
        if not value:
            continue
        for principal in re.split(r"[,\s]+", value.strip()):
            if principal and not _PRINCIPAL.match(principal):
                raise ValueError(f"'{field}' contains an invalid user or group: {principal!r}")
    for field in ("force_user", "force_group"):
        value = (getattr(share, field) or "").strip()
        if value and not _UNIX_NAME.match(value):
            raise ValueError(f"'{field}' must be a plain user or group name")
    for field in ("quota_gb", "timemachine_quota_gb"):
        value = getattr(share, field)
        if value is not None and not (0 <= int(value) <= 1_000_000):
            raise ValueError(f"'{field}' is out of range")


class SambaStatus(BaseModel):
    running: bool
    mode: str  # "native_sidecar", "host_auditor", "disabled", "host_native"
    port_445_open: bool
    shares_count: int
    sidecar_detected: bool = False
    sidecar_status: str = "not_found"
    config_path: str = Field(default_factory=lambda: SAMBA_CONF_FILE)  # not in the API schema: it depends on the host
    native_samba_active: bool = False


# Run inside the file server's container when its settings changed. Restarting the container
# cut every connection, also for a change that concerned one shared folder or one blocked address.
# Samba applies reloaded settings to new connections only, so the shared folders whose section
# changed are closed (their clients connect again, under the new settings) and the connections of
# newly blocked addresses are ended; everything else stays connected. The first lines make the
# accounts Samba's own list has and the container lacks (after a restore), as its start does.
# Arguments: the shared folders to close, then "--ips" and the addresses to end.
# Each person's own account in the file server's container (KB_UIDS: "name:number ..."), so they
# sign in as themselves and their private folder can be theirs: made with that number in the
# users group, or made again when an older one had another number.
ACCOUNTS_SCRIPT = """
for pair in $KB_UIDS; do
  user=${pair%%:*}; want=${pair##*:}
  have=$(id -u "$user" 2>/dev/null)
  [ "$have" = "$want" ] && continue
  [ -n "$have" ] && deluser "$user" 2>/dev/null
  adduser -D -H -u "$want" -G users "$user" 2>/dev/null || adduser -D -H -u "$want" "$user" 2>/dev/null
done
"""

RELOAD_SCRIPT = (
    ACCOUNTS_SCRIPT
    + """
CONF=/etc/samba/kiboto/smb.conf
pdbedit -L 2>/dev/null | while IFS=: read -r user uid _; do
  [ -n "$user" ] && ! id -u "$user" >/dev/null 2>&1 && { adduser -D -H -u "$uid" "$user" 2>/dev/null || adduser -D -H "$user"; }
done
smbcontrol --configfile="$CONF" all reload-config || exit 1
kind=share
for a in "$@"; do
  if [ "$a" = "--ips" ]; then kind=ip; continue; fi
  if [ "$kind" = share ]; then smbcontrol --configfile="$CONF" all close-share "$a"
  else smbcontrol --configfile="$CONF" all kill-client-ip "$a"; fi
done
exit 0
"""
)


def conf_sections(text: str) -> dict[str, str]:
    """An smb.conf text by section: name -> its lines."""
    out: dict[str, list[str]] = {}
    name = ""
    for line in text.splitlines():
        head = re.fullmatch(r"\[([^\]]+)\]", line.strip())
        if head:
            name = head.group(1)
            out[name] = []
        elif name and line.strip():
            out[name].append(line.strip())
    return {n: "\n".join(lines) for n, lines in out.items()}


def _denied(section: str) -> set[str]:
    found = re.search(r"^hosts deny = (.*)$", section, re.M)
    return set(found.group(1).split()) if found else set()


def _people(section: str) -> tuple[set[str] | None, set[str], list[str]]:
    """A share's section as (who may open it, or None when it does not say; who may only read; the other lines)."""
    valid: set[str] | None = None
    readers: set[str] = set()
    rest = []
    for line in section.splitlines():
        if line.startswith("valid users = "):
            valid = set(line.split("=", 1)[1].split())
        elif line.startswith("read list = "):
            readers = set(line.split("=", 1)[1].split())
        else:
            rest.append(line)
    return valid, readers, rest


def only_lets_more_in(was: str, now: str) -> bool:
    """Whether a share's new section takes nothing from anyone: it differs only in people added
    to those who may open it (a new person), or in someone who may now write. The connections
    that are open stay right, so they need not be closed."""
    valid0, read0, rest0 = _people(was)
    valid1, read1, rest1 = _people(now)
    if rest0 != rest1 or valid0 is None or valid1 is None:
        return False
    return valid0 <= valid1 and read1 <= read0 | (valid1 - valid0)


def what_changed(old: str, new: str) -> dict[str, Any]:
    """What a new smb.conf changes against the one before: the shared folders to close ("shares":
    the section is gone, or different in a way that takes something from someone), the addresses
    blocked now and not before ("ips"), and whether the private folders' section changed
    ("homes": they are shares named after each person, so they cannot be closed by name)."""
    was, now = conf_sections(old), conf_sections(new)
    special = ("global", "homes")
    shares = sorted(
        n
        for n in was
        if n not in special and was[n] != now.get(n) and not (n in now and only_lets_more_in(was[n], now[n]))
    )
    return {
        "shares": shares,
        "ips": sorted(_denied(now.get("global", "")) - _denied(was.get("global", ""))),
        "homes": was.get("homes") != now.get("homes") and "homes" in was,
    }


def accounts_file_replaced() -> bool:
    """Whether Samba's list of accounts (passdb.tdb) is another file than at the last look. A
    settings restore or a takeover puts a new file in its place, and the running file server
    keeps the old one open: after a reload a person from the new list is refused and one who is
    no longer in it still gets in (tried with the real smbd). Only a restart makes it use the new
    list. Samba itself changes the file in place, which this does not count. The first look on an
    install that has such a list counts as replaced: nothing is known about it yet."""
    try:
        st = os.stat(PASSDB_FILE)
        mark = f"{st.st_dev}:{st.st_ino}"
    except OSError:
        mark = ""
    try:
        with open(PASSDB_SEEN_FILE, encoding="utf-8") as f:
            was: str | None = f.read().strip()
    except OSError:
        was = None
    if was != mark:
        try:
            atomic_write_text(PASSDB_SEEN_FILE, mark)
        except OSError:
            logger.debug("[SambaEngine] could not note the accounts file", exc_info=True)
    return bool(mark) and was != mark


def _both(first: dict[str, Any] | None, second: dict[str, Any] | None) -> dict[str, Any] | None:
    """Two sets of changes as one; unknown when either is."""
    if first is None or second is None:
        return None
    return {
        "shares": sorted(set(first["shares"]) | set(second["shares"])),
        "ips": sorted(set(first["ips"]) | set(second["ips"])),
        "homes": first["homes"] or second["homes"],
    }


def _serves_files() -> bool:
    """Whether the shared folders are Kiboto's own to make (not Unraid's or another host's)."""
    from backend.hardware.pal_storage import get_storage_platform

    try:
        return bool(get_storage_platform().get_capabilities().can_manage_shares)
    except (OSError, RuntimeError, ValueError):
        return False


SMB_WAITING_FILE = os.path.join(DATA_DIR, "smb_waiting.json")


@json_locked(lambda username, ok: SMB_WAITING_FILE)
def note_password_handed(username: str, ok: bool) -> None:
    """Whether Samba took this person's password. Kept only where Kiboto's own Samba serves files."""
    waiting = read_json(SMB_WAITING_FILE, [])
    waiting = [w for w in waiting if isinstance(w, str)] if isinstance(waiting, list) else []
    name = username.lower()
    if ok and name not in waiting:
        return
    if not ok and (name in waiting or not _serves_files()):
        return
    atomic_write_json(SMB_WAITING_FILE, sorted({*waiting, name} if not ok else set(waiting) - {name}))


def waiting_for_password(username: str) -> bool:
    """Whether Samba still waits for this person's password (it did not take the last one)."""
    waiting = read_json(SMB_WAITING_FILE, [])
    return isinstance(waiting, list) and username.lower() in waiting


def serves_files() -> bool:
    """_serves_files for other modules (the NFS side hands folders over the same way)."""
    return _serves_files()


class SambaEngine:
    """
    Manages Samba daemon configuration, shares lifecycle, and sidecar integration.
    """

    _DEFAULT_GLOBAL_CONFIG = """[global]
   workgroup = WORKGROUP
   server string = Kiboto Storage Server
   server role = standalone server
   security = user
   map to guest = Bad User
   dns proxy = no
   usershare allow guests = yes

   # Line-rate 10GbE & Multi-Channel performance tuning
   min protocol = SMB2_10
   server multi channel support = yes
   aio read size = 1
   aio write size = 1
   deadtime = 15

   # Apple macOS Finder & Time Machine enhancements (vfs_fruit)
   vfs objects = catia fruit streams_xattr
   fruit:metadata = netatalk
   fruit:model = MacPro
   # Shared folders write as one user (force user); a Mac setting a folder's permissions through
   # its NFS ACEs made each new folder that user's alone (700), and the Mac then refused to write
   # into it (found copying a folder from a Mac). Without them new folders keep the share's masks.
   fruit:nfs_aces = no
   fruit:posix_rename = yes
   fruit:veto_appledouble = no
   fruit:wipe_intentionally_left_blank_rfork = yes
   fruit:delete_empty_adfiles = yes
"""

    def __init__(self):
        os.makedirs(SAMBA_DIR, exist_ok=True)
        private_dir = os.path.join(SAMBA_DIR, "private")
        try:
            os.makedirs(private_dir, mode=0o700, exist_ok=True)
            os.chmod(private_dir, 0o700)
        except OSError:
            pass
        self._shares: dict[str, SambaShareConfig] = {}
        self._load_shares()
        self.sync_sidecar_policy()
        self._ensure_default_conf()
        # On a managed host the machine's Samba reads Kiboto's settings from the first moment: a
        # password set before that would go into Debian's own list of accounts and be lost.
        if samba_host.active() and samba_host.point_samba_here(SAMBA_CONF_FILE):
            samba_host.reload(None, _host_numbers())

    def sync_sidecar_policy(self) -> tuple[bool, str]:
        """Ensures disable_sidecar marker exists when host has native Samba active or is a turnkey OS."""
        can_run, reason = self.can_run_sidecar()
        marker_file = os.path.join(SAMBA_DIR, "disable_sidecar")
        if not can_run:
            try:
                with open(marker_file, "w", encoding="utf-8") as f:
                    f.write(f"disabled: {reason}\n")
            except Exception as e:
                logger.debug(f"[SambaEngine] Could not write disable_sidecar marker: {e}")
        else:
            if os.path.isfile(marker_file):
                try:
                    os.remove(marker_file)
                except Exception:
                    ignored("backend.services.samba_engine.SambaEngine.sync_sidecar_policy")
        return can_run, reason

    def can_run_sidecar(self) -> tuple[bool, str]:
        """Pre-flight check to verify if zettnas-samba sidecar can bind port 445."""
        if samba_host.active():
            return False, "This machine serves files itself."
        from backend.hardware.pal.base import PlatformType
        from backend.hardware.pal.detect import StoragePlatformDetector

        platform = StoragePlatformDetector.detect()
        if platform in (
            PlatformType.UNRAID,
            PlatformType.TRUENAS,
            PlatformType.PROXMOX,
            PlatformType.FYGOOS,
            PlatformType.ZETTOS,
            PlatformType.UGOS,
            PlatformType.GENERIC_OBSERVER,
        ):
            return False, f"Host is running {platform.value} with native host storage/SMB services."

        sidecar_info = self.check_sidecar()
        is_sidecar_running = sidecar_info.get("detected") and sidecar_info.get("state") == "running"
        if not is_sidecar_running and self.check_port_445():
            return False, "Port 445 is already bound on host by an existing SMB daemon."

        return True, "Ready"

    def _ensure_default_conf(self) -> None:
        """Ensures smb.conf exists with initial configuration if missing."""
        if not os.path.isfile(SAMBA_CONF_FILE):
            self.generate_and_save_conf()

    def _load_shares(self) -> None:
        """Loads configured shares from JSON storage."""
        if os.path.isfile(SAMBA_SHARES_FILE):
            try:
                with open(SAMBA_SHARES_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            try:
                                share = SambaShareConfig(**item)
                                self._shares[share.name] = share
                            except Exception:
                                ignored("backend.services.samba_engine.SambaEngine._load_shares")
            except Exception as e:
                logger.debug(f"[SambaEngine] Failed loading shares JSON: {e}")

        # If no shares exist yet and default pool path exists, configure a default share. Not on a
        # machine set up for Kiboto: its main storage folder is on the system disk, and the first
        # share is made on the first pool when that is made (system_disk.default_share_after_pool)
        from backend import runtime

        if not self._shares and not runtime.managed_host():
            default_path = os.path.join(POOL_PATH, "shares") if POOL_PATH else "/mnt/storage"
            default_share = SambaShareConfig(
                name="storage",
                path=default_path,
                comment="Kiboto Primary Storage Pool",
                read_only=False,
                guest_ok=False,
                browseable=True,
                timemachine=False,
            )
            self._shares[default_share.name] = default_share
            self._save_shares_json()

    def _save_shares_json(self) -> None:
        """Persists configured shares to JSON."""
        try:
            atomic_write_json(SAMBA_SHARES_FILE, [s.model_dump() for s in self._shares.values()], indent=2)
        except Exception as e:
            logger.error(f"[SambaEngine] Failed writing shares JSON: {e}")

    def list_shares(self) -> list[SambaShareConfig]:
        """Returns all configured Samba shares."""
        return list(self._shares.values())

    def get_share(self, name: str) -> SambaShareConfig | None:
        """Returns share by name."""
        return self._shares.get(name)

    def add_or_update_share(self, share: SambaShareConfig) -> SambaShareConfig:
        """Adds or updates a Samba share and regenerates smb.conf."""
        validate_share(share)
        # Validate name (safe SMB share name)
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", share.name.strip())
        if not clean_name or clean_name.lower() in ("global", "homes", "printers", "ipc$"):
            raise SaidError("Share name cannot be empty, invalid or reserved", "share_bad_name")
        share.name = clean_name

        # Ensure directory exists if possible
        try:
            if not os.path.exists(share.path):
                os.makedirs(share.path, exist_ok=True)
        except Exception as e:
            logger.warning(f"[SambaEngine] Could not create share directory {share.path}: {e}")

        self._shares[share.name] = share
        self._save_shares_json()
        self.generate_and_save_conf()
        self.reload_service()
        return share

    def remove_share(self, name: str) -> bool:
        """Removes a share and regenerates smb.conf."""
        if name in self._shares:
            del self._shares[name]
            self._save_shares_json()
            self.generate_and_save_conf()
            self.reload_service()
            return True
        return False

    def generate_and_save_conf(self) -> str:
        """Generates the full smb.conf text and saves it to disk."""
        glob = self._DEFAULT_GLOBAL_CONFIG.strip()
        if not any(getattr(s, "guest_ok", False) for s in self._shares.values()):
            # B11 (SEC-22): no guest share, so a wrong password is refused, never mapped to guest
            glob = glob.replace("map to guest = Bad User", "map to guest = Never")
        if samba_host.active():  # the machine's own smbd: told what the container's image sets
            glob += "\n" + "\n".join(samba_host.global_lines(SAMBA_DIR))
        conf_lines = [glob]
        from backend.services import ip_block
        from backend.services.ransomware_guard import get_guard

        blocked = [b["ip"] for b in ip_block.list_blocks()]
        if blocked:
            conf_lines.append(f"   hosts deny = {' '.join(blocked)}")  # M5
        frozen = get_guard().frozen  # M4: every share read-only while frozen
        conf_lines.append("")

        # Private folders (Batch 6): each signed-in person sees only their own as a share named after them.
        # Written as the shared folders are (as nobody:users), so the folder and what the Files app puts
        # in it have one owner; who may open it is decided by "valid users", as before.
        ours = _serves_files()
        try:
            from backend.services.user_spaces import homes_root

            if os.path.isdir(homes_root()):
                conf_lines.extend(
                    [
                        "[homes]",
                        f"   path = {homes_root()}/%S",
                        "   valid users = %S",
                        "   browseable = no",
                        f"   read only = {'yes' if frozen else 'no'}",
                        # on Kiboto's own file server each home's access list keeps the group and
                        # everyone else out, and these group bits are its mask: Kiboto's own user
                        # (the web page) can still open what a person saves over the network
                        f"   create mask = {'0660' if ours else '0600'}",
                        f"   directory mask = {'0770' if ours else '0700'}",
                        "",
                    ]
                )
                if ours:  # each person signs in as their own account, and their folder is theirs
                    from backend.services import smb_accounts

                    known = _people_names()
                    for person in os.listdir(homes_root()):
                        if person.lower() in known:
                            owned.to_person(os.path.join(homes_root(), person), smb_accounts.uid_of(person))
        except Exception:
            logger.debug("[SambaEngine] homes section skipped", exc_info=True)

        for share in self._shares.values():
            try:
                validate_share(share)
            except ValueError as e:
                logger.error("[SambaEngine] Skipping share '%s' with unsafe settings: %s", share.name, e)
                continue
            if ours and share.force_user:  # the file server writes as that user: the folder is theirs
                owned.to_people(share.path, share.force_user, share.force_group or "users")
            conf_lines.append(f"[{share.name}]")
            conf_lines.append(f"   path = {share.path}")
            if share.comment:
                conf_lines.append(f"   comment = {share.comment}")
            conf_lines.append(f"   browseable = {'yes' if share.browseable else 'no'}")
            conf_lines.append(f"   read only = {'yes' if share.read_only or frozen else 'no'}")
            conf_lines.append(f"   guest ok = {'yes' if share.guest_ok else 'no'}")
            conf_lines.append("   create mask = 0775")
            conf_lines.append("   directory mask = 0775")
            if share.force_user:
                conf_lines.append(f"   force user = {share.force_user}")
            if share.force_group:
                conf_lines.append(f"   force group = {share.force_group}")

            veto = protected_veto_names(share.path)
            if veto:
                conf_lines.append("   veto files = " + "".join(f"/{n}/" for n in veto))
                conf_lines.append("   delete veto files = no")
            if share.valid_users:
                conf_lines.append(f"   valid users = {share.valid_users}")
            if share.read_list:
                conf_lines.append(f"   read list = {share.read_list}")
            if share.write_list:
                conf_lines.append(f"   write list = {share.write_list}")
            try:
                conf_lines.extend(access_lines(share))
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as e:  # never open by accident
                logger.error("[SambaEngine] Share access for '%s' unreadable, share switched off: %s", share.name, e)
                conf_lines.append("   available = no")

            vfs = ["catia", "fruit", "streams_xattr"]
            if share.previous_versions:
                # Windows "Previous Versions" from the scheduled snapshots
                # (<pool>/@snapshots/<share>@auto-YYYYMMDD-HHMM, see snapshot_service)
                snapdir = _snapshot_dir_for(share.path)
                if snapdir:
                    vfs.append("shadow_copy2")
                    conf_lines.append(f"   shadow:snapdir = {snapdir}")
                    conf_lines.append(f"   shadow:basedir = {share.path}")
                    conf_lines.append(f"   shadow:format = {share.name}@auto-%Y%m%d-%H%M")
                    conf_lines.append("   shadow:sort = desc")
                    conf_lines.append("   shadow:localtime = no")  # snapshot names are UTC (NREL-15)

            if share.recycle_bin:
                vfs.append("recycle")
                conf_lines += [
                    "   recycle:repository = .RecycleBin/files",
                    "   recycle:keeptree = no",
                    "   recycle:versions = yes",
                    "   recycle:touch_mtime = yes",
                    "   recycle:directory_mode = 0770",
                    "   recycle:exclude = *.tmp,~$*,.~lock.*",
                    "   recycle:exclude_dir = .RecycleBin",
                ]
            if len(vfs) > 3:
                conf_lines.append("   vfs objects = " + " ".join(vfs))

            if share.timemachine:
                conf_lines.append("   fruit:time machine = yes")
                if share.timemachine_quota_gb and share.timemachine_quota_gb > 0:
                    conf_lines.append(f"   fruit:time machine max size = {share.timemachine_quota_gb}G")
            elif share.quota_gb and share.quota_gb > 0:
                conf_lines.append(f"   # storage quota = {share.quota_gb}G")

            conf_lines.append("")

        full_conf = "\n".join(conf_lines)
        try:
            with open(SAMBA_CONF_FILE, encoding="utf-8") as f:
                now: dict[str, Any] | None = what_changed(f.read(), full_conf)  # for reload_service: what to close
        except OSError:
            now = None  # no settings before: nothing is known, the server is restarted
        # settings written twice before one reload: what the first writing changed still counts
        self._changed = _both(self._changed, now) if getattr(self, "_pending", False) else now
        self._pending = True
        try:
            atomic_write_text(SAMBA_CONF_FILE, full_conf)  # Samba never reads half a file (REL-22)
            logger.info("[SambaEngine] Generated and saved smb.conf with %s shares", len(self._shares))
        except Exception as e:
            logger.error(f"[SambaEngine] Failed writing smb.conf: {e}")

        return full_conf

    def get_config_text(self) -> str:
        """Returns the current content of smb.conf."""
        if os.path.isfile(SAMBA_CONF_FILE):
            try:
                with open(SAMBA_CONF_FILE, encoding="utf-8") as f:
                    return f.read()
            except Exception:
                ignored("backend.services.samba_engine.SambaEngine.get_config_text")
        return self.generate_and_save_conf()

    def check_port_445(self) -> bool:
        """Tests if SMB port 445 is accepting TCP connections."""
        targets = ["127.0.0.1", "localhost"]
        try:
            from backend.state import Z_STATE

            host_ip = getattr(Z_STATE, "discovered_host_ip", None) or _settings.current("host_ip")
            if host_ip and host_ip not in targets:
                targets.append(host_ip)
        except Exception:
            ignored("backend.services.samba_engine.SambaEngine.check_port_445")
        for target in targets:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.4)
                res = s.connect_ex((target, 445))
                s.close()
                if res == 0:
                    return True
            except Exception:
                ignored("backend.services.samba_engine.SambaEngine.check_port_445")
        return False

    def check_sidecar(self) -> dict[str, Any]:
        """Inspects Docker for running zettnas-samba sidecar container if docker socket is accessible."""
        docker_sock = _docker_sock_path()
        if not os.path.exists(docker_sock):
            return {"detected": False, "status": "no_docker_socket"}

        try:
            import httpx

            transport = httpx.HTTPTransport(uds=docker_sock)
            with httpx.Client(transport=transport, timeout=1.5) as client:
                r = client.get("http://localhost/containers/json?all=1")
                if r.status_code == 200:
                    containers = r.json()
                    for c in containers:
                        names = [n.lstrip("/") for n in c.get("Names", [])]
                        if {"kiboto-samba", legacy_names.OLD_SAMBA} & set(names):
                            return {
                                "detected": True,
                                "id": c.get("Id", "")[:12],
                                "state": c.get("State", "unknown"),
                                "status": c.get("Status", ""),
                            }
        except Exception as e:
            logger.debug("[SambaEngine] Docker socket inspection error: %s", e)

        return {"detected": False, "status": "not_found"}

    def reload_service(self) -> bool:
        """Attempts to signal smbd or restart the Samba sidecar (kiboto-samba, or zettnas-samba from before)."""
        if samba_host.active():  # the machine's own file server, driven directly
            changed, self._changed, self._pending = getattr(self, "_changed", None), None, False
            if accounts_file_replaced() or samba_host.point_samba_here(SAMBA_CONF_FILE):
                changed = None
            return samba_host.reload(changed, _host_numbers())
        # 1. Try smbcontrol if available in container/host
        try:
            res = subprocess.run(["smbcontrol", "all", "reload-config"], capture_output=True, timeout=2)
            if res.returncode == 0:
                logger.info("[SambaEngine] smbcontrol reload-config succeeded")
                return True
        except (FileNotFoundError, subprocess.SubprocessError):
            pass

        # 2. The sidecar container: its settings reloaded in place where that is enough, else a restart
        changed, self._changed, self._pending = getattr(self, "_changed", None), None, False
        if accounts_file_replaced():
            changed = None  # a new list of accounts: the file server has to start again to use it
        docker_sock = _docker_sock_path()
        sidecar_info = self.check_sidecar()
        if os.path.exists(docker_sock) and sidecar_info.get("detected"):
            try:
                import httpx

                transport = httpx.HTTPTransport(uds=docker_sock)
                with httpx.Client(transport=transport, timeout=20.0) as client:
                    cid = sidecar_info.get("id") or "kiboto-samba"
                    env = _accounts_env()
                    if changed is not None and not changed["homes"] and _reload_in_place(client, cid, changed, env):
                        logger.info(
                            "[SambaEngine] settings reloaded without a restart; closed: %s",
                            ", ".join(changed["shares"]) or "nothing",
                        )
                        return True
                    if env:
                        _run_accounts(client, cid, env)
                    r = client.post(
                        f"http://localhost/containers/{sidecar_info.get('id') or 'kiboto-samba'}/restart?t=2"
                    )
                    if r.status_code in (204, 200):
                        logger.info("[SambaEngine] Samba sidecar restarted successfully")
                        return True
            except Exception:
                ignored("backend.services.samba_engine.SambaEngine.reload_service")

        return False

    def sync_samba_user(self, username: str, password: str | None = None, delete: bool = False) -> bool:
        """Puts a person's password into Samba (or takes them out with delete=True). Samba gets a
        password only when Kiboto knows it in plain words, so one it did not take (its service not
        up yet) is kept in mind and handed over again at the person's next sign-in (#71: the admin
        was missing from Samba, and every network sign-in failed until the password was changed)."""
        ok = self._sync_samba_user(username, password=password, delete=delete)
        if delete or password:
            note_password_handed(username, ok or delete)
        return ok

    def _sync_samba_user(self, username: str, password: str | None = None, delete: bool = False) -> bool:
        """
        Synchronizes a user into the Samba passdb database.
        When delete=True, removes the user from passdb.
        When password is provided, creates or updates the SMB credentials.
        """
        if not re.fullmatch(r"^[a-zA-Z0-9_\-\.]{1,32}$", username):
            logger.warning("[SambaEngine] Rejected invalid username for passdb sync: '%s'", username)
            return False
        if samba_host.active():
            if delete:
                return samba_host.remove(username)
            if not password:
                return False
            from backend.services import smb_accounts

            return samba_host.set_password(username, smb_accounts.uid_of(username), password)

        sidecar_info = self.check_sidecar()
        docker_sock = _docker_sock_path()
        person_env: list[str] = []
        if _serves_files() and not delete:  # their own account, by their fixed number
            from backend.services import smb_accounts

            person_env = [f"KB_UIDS={username.lower()}:{smb_accounts.uid_of(username)}"]

        # 1. Try local execution if smbpasswd exists on the system
        try:
            if delete:
                res = subprocess.run(["smbpasswd", "-x", username], capture_output=True, timeout=3)
                if res.returncode == 0:
                    logger.info(f"[SambaEngine] Removed user '{username}' from passdb.")
                    return True
            elif password:
                subprocess.run(["adduser", "-D", "-H", username], capture_output=True, timeout=2)
                p = subprocess.Popen(
                    ["smbpasswd", "-a", "-s", username],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                p.communicate(f"{password}\n{password}\n", timeout=3)
                if p.returncode == 0:
                    logger.info("[SambaEngine] Synchronized user '%s' into passdb.", username)
                    return True
        except (FileNotFoundError, subprocess.SubprocessError):
            pass

        # 2. Try docker exec into zettnas-samba container
        if sidecar_info.get("detected") and os.path.exists(docker_sock):
            try:
                import httpx

                transport = httpx.HTTPTransport(uds=docker_sock)
                with httpx.Client(transport=transport, timeout=5.0) as client:
                    cid = sidecar_info.get("id", "kiboto-samba")
                    if delete:
                        create_exec = client.post(
                            f"http://localhost/containers/{cid}/exec",
                            json={"Cmd": ["smbpasswd", "-x", username], "AttachStdout": True, "AttachStderr": True},
                        )
                        if create_exec.status_code == 201:
                            exec_id = create_exec.json().get("Id")
                            client.post(f"http://localhost/exec/{exec_id}/start", json={"Detach": False, "Tty": False})
                            logger.info("[SambaEngine] Removed user '%s' from sidecar passdb.", username)
                            return True
                    elif password:
                        u_exec = client.post(
                            f"http://localhost/containers/{cid}/exec",
                            json={
                                "Cmd": [
                                    "sh",
                                    "-c",
                                    'id -u "$1" >/dev/null 2>&1 || adduser -D -H -u 1000 "$1" 2>/dev/null || adduser -D -H "$1"',  # 1000 once, then the next free id
                                    "--",
                                    username,
                                ]
                                if not person_env
                                else ["sh", "-c", ACCOUNTS_SCRIPT],
                                "Env": person_env,
                                "AttachStdout": True,
                                "AttachStderr": True,
                            },
                        )
                        if u_exec.status_code == 201:
                            client.post(
                                f"http://localhost/exec/{u_exec.json().get('Id')}/start",
                                json={"Detach": False, "Tty": False},
                            )

                        p_exec = client.post(
                            f"http://localhost/containers/{cid}/exec",
                            json={
                                "Cmd": [
                                    "sh",
                                    "-c",
                                    'printf "%s\\n%s\\n" "$SMB_PASS" "$SMB_PASS" | smbpasswd -a -s "$1"',
                                    "--",
                                    username,
                                ],
                                "Env": [f"SMB_PASS={password}"],
                                "AttachStdout": True,
                                "AttachStderr": True,
                            },
                        )
                        if p_exec.status_code == 201:
                            client.post(
                                f"http://localhost/exec/{p_exec.json().get('Id')}/start",
                                json={"Detach": False, "Tty": False},
                            )
                            logger.info("[SambaEngine] Synchronized user '%s' into sidecar passdb.", username)
                            return True
            except Exception as e:
                logger.debug(f"[SambaEngine] Docker exec passdb sync error: {e}")

        return False

    def set_account_enabled(self, username: str, enabled: bool) -> bool:
        """Turns a person's network-share account off or on, keeping its password.

        A person who was turned off kept reaching their private folder and every open share over
        the network: only the web session was ended (SET-10)."""
        if not re.fullmatch(r"^[a-zA-Z0-9_\-\.]{1,32}$", username):
            return False
        if samba_host.active():
            return samba_host.set_enabled(username, enabled)
        cmd = ["smbpasswd", "-e" if enabled else "-d", username]
        try:
            if subprocess.run(cmd, capture_output=True, timeout=3).returncode == 0:
                logger.info("[SambaEngine] Network account of '%s' %s.", username, "on" if enabled else "off")
                return True
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            logger.debug("[SambaEngine] no local smbpasswd for %s (%s): trying the Samba container", username, e)
        sidecar_info = self.check_sidecar()
        docker_sock = _docker_sock_path()
        if not (sidecar_info.get("detected") and os.path.exists(docker_sock)):
            return False
        try:
            import httpx

            with httpx.Client(transport=httpx.HTTPTransport(uds=docker_sock), timeout=5.0) as client:
                cid = sidecar_info.get("id", "kiboto-samba")
                made = client.post(
                    f"http://localhost/containers/{cid}/exec",
                    json={"Cmd": cmd, "AttachStdout": True, "AttachStderr": True},
                )
                if made.status_code != 201:
                    return False
                client.post(
                    f"http://localhost/exec/{made.json().get('Id')}/start", json={"Detach": False, "Tty": False}
                )
                logger.info("[SambaEngine] Network account of '%s' %s (sidecar).", username, "on" if enabled else "off")
                return True
        except (OSError, ValueError, RuntimeError, httpx.HTTPError) as e:
            logger.debug("[SambaEngine] could not switch the network account of %s: %s", username, e)
            return False

    def get_status(self) -> SambaStatus:
        """Returns comprehensive status of Samba file sharing service."""
        port_open = self.check_port_445()
        if samba_host.active():
            return SambaStatus(
                running=samba_host.running(),
                mode="host_native",
                port_445_open=port_open,
                shares_count=len(self._shares),
                sidecar_detected=False,
                sidecar_status="not_needed",
                config_path=SAMBA_CONF_FILE,
                native_samba_active=True,
            )
        sidecar_info = self.check_sidecar()
        sidecar_detected = sidecar_info.get("detected", False)
        is_sidecar_running = sidecar_detected and sidecar_info.get("state") == "running"

        from backend.hardware.pal.base import PlatformType
        from backend.hardware.pal.detect import StoragePlatformDetector

        platform = StoragePlatformDetector.detect()
        is_turnkey = platform in (
            PlatformType.UNRAID,
            PlatformType.TRUENAS,
            PlatformType.PROXMOX,
            PlatformType.FYGOOS,
            PlatformType.ZETTOS,
            PlatformType.UGOS,
            PlatformType.GENERIC_OBSERVER,
        )

        self.sync_sidecar_policy()
        native_samba = is_turnkey or (port_open and not is_sidecar_running)

        if is_turnkey:
            mode = "host_native" if platform == PlatformType.ZETTOS else "host_auditor"
            running = port_open
            sidecar_status = "standby_host_native" if sidecar_detected else sidecar_info.get("status", "not_found")
        elif is_sidecar_running:
            mode = "native_sidecar"
            running = True
            sidecar_status = sidecar_info.get("status", "running")
        else:
            mode = "native_sidecar" if platform == PlatformType.GENERIC_LINUX else "host_auditor"
            running = port_open
            sidecar_status = sidecar_info.get("status", "not_found")

        return SambaStatus(
            running=running,
            mode=mode,
            port_445_open=port_open,
            shares_count=len(self._shares),
            sidecar_detected=sidecar_detected,
            sidecar_status=sidecar_status,
            config_path=SAMBA_CONF_FILE,
            native_samba_active=native_samba,
        )


_SAMBA_ENGINE_INSTANCE: SambaEngine | None = None


SMB_NAME = re.compile(r"^[a-zA-Z0-9_\-\.]{1,32}$")


def access_lines(share: "SambaShareConfig") -> list[str]:
    """smb.conf lines that make SMB follow share access (B11, SEC-28; warned in 1.11, written since
    1.12 per D11). Lists set on the share itself win, as they do in share access; a guest share
    stays open; a share nobody may open is switched off. The people who may open it are always
    named: nobody else's account opens it."""
    if share.guest_ok or share.valid_users or share.read_list or share.write_list:
        return []
    from backend.services.share_access import load_config, share_level
    from backend.users_db import list_users

    cfg = load_config()
    admins = _files_admin_roles()
    levels = {}
    for u in list_users():
        name = str(u.get("username") or "")
        if u.get("status") != "active" or not SMB_NAME.match(name):
            continue
        role = u.get("role_id") or ""
        if role in admins:
            # an administrator opens every shared folder, as in Files, whatever the folder's own
            # list says (SET-01, the owner's decision S1: always in; a new folder used to be off
            # for its owner too)
            levels[name] = "write"
        else:
            levels[name] = share_level(cfg, share.name, name, role)
    # Written out also when everyone may write. Left to Samba's default ("anyone with an account"),
    # an account that stayed in Samba's own list after its person was removed or switched off here
    # (the file server could not be told at that moment) kept opening the folder.
    allowed = sorted(u for u, v in levels.items() if v in ("read", "write"))
    if not allowed:
        return ["   available = no"]
    lines = [f"   valid users = {' '.join(allowed)}"]
    readers = sorted(u for u, v in levels.items() if v == "read")
    if readers and not share.read_only:
        lines.append(f"   read list = {' '.join(readers)}")
    return lines


def _files_admin_roles() -> set[str]:
    """The roles that manage every folder in Files (path_access._is_files_admin)."""
    import json

    from backend.auth import has_scope
    from backend.users_db import users_db_session

    with users_db_session(None, readonly=True) as conn:
        rows = conn.execute("SELECT id, scopes_json FROM roles").fetchall()
    out = set()
    for row in rows:
        try:
            scopes = json.loads(row["scopes_json"] or "[]")
        except ValueError:
            continue
        if "superadmin" in scopes or has_scope(scopes, "storage:admin") or has_scope(scopes, "shares:manage"):
            out.add(row["id"])
    return out


def _people_names() -> set[str]:
    """The Kiboto accounts there are now (lower case)."""
    from backend.users_db import list_users

    return {str(u.get("username") or "").lower() for u in list_users() if u.get("username")}


def _host_numbers() -> dict[str, int]:
    """Every person's account number, for the machine's own users."""
    from backend.services import smb_accounts

    try:
        return smb_accounts.numbers(_people_names())
    except (OSError, ValueError, sqlite3.Error):
        return {}


def _accounts_env() -> list[str]:
    """KB_UIDS for the scripts: every person's account number where Kiboto serves the files."""
    if not _serves_files():
        return []
    from backend.services import smb_accounts

    try:
        pairs = smb_accounts.numbers(_people_names())
    except (OSError, ValueError, sqlite3.Error):
        return []
    return ["KB_UIDS=" + " ".join(f"{name}:{uid}" for name, uid in pairs.items())] if pairs else []


def _run_accounts(client: Any, cid: str, env: list[str]) -> None:
    """The people's accounts in the container, before it starts again (a restart keeps them)."""
    made = client.post(
        f"http://localhost/containers/{cid}/exec",
        json={"Cmd": ["sh", "-c", ACCOUNTS_SCRIPT], "Env": env, "AttachStdout": True, "AttachStderr": True},
    )
    if made.status_code == 201:
        client.post(f"http://localhost/exec/{made.json().get('Id')}/start", json={"Detach": False, "Tty": False})


def _reload_in_place(client: Any, cid: str, changed: dict[str, Any], env: list[str] | None = None) -> bool:
    """Runs RELOAD_SCRIPT in the file server's container; True when it ended well."""
    body: dict[str, Any] = {
        "Cmd": ["sh", "-c", RELOAD_SCRIPT, "--", *changed["shares"], "--ips", *changed["ips"]],
        "AttachStdout": True,
        "AttachStderr": True,
    }
    if env:
        body["Env"] = env
    made = client.post(f"http://localhost/containers/{cid}/exec", json=body)
    if made.status_code != 201:
        return False
    exec_id = made.json().get("Id")
    client.post(f"http://localhost/exec/{exec_id}/start", json={"Detach": False, "Tty": False})
    said = client.get(f"http://localhost/exec/{exec_id}/json")
    return said.status_code == 200 and said.json().get("ExitCode") == 0


def refresh_access() -> None:
    """Rewrites smb.conf and reloads Samba after share access or the people change (SEC-28).
    Nothing to do where Kiboto manages no shares (Unraid, TrueNAS)."""
    try:
        engine = get_samba_engine()
        if engine.list_shares():
            engine.generate_and_save_conf()
            engine.reload_service()
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error):
        ignored("backend.services.samba_engine.refresh_access")


def get_samba_engine() -> SambaEngine:
    global _SAMBA_ENGINE_INSTANCE
    if _SAMBA_ENGINE_INSTANCE is None:
        _SAMBA_ENGINE_INSTANCE = SambaEngine()
    return _SAMBA_ENGINE_INSTANCE
