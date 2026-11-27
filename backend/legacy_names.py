"""Names from before the Kiboto rebrand (ZettNAS) that the code still has to know.

Accepted until Kiboto 2.2 (REMOVE_IN), then removed with this file: the ZETTNAS_* environment
variables existing installs set, and the other old names added here as the rename goes on.

Kept here because data made before depends on them, each with its one-time move: the data key's
salt (db_crypto re-encrypts), the secret box's key and associated data (key_rotation re-seals), the
backup manifest name and config-export prefix that restores still read (backup_engine), and the
restic tag on off-site snapshots (offsite_backup). Changing those would make that data unreadable.
The same goes for names stored outside Kiboto's data: replication's ZFS snapshot names
(zettnas-repl-, the next incremental send's base), the encrypted-dataset and data-id properties,
the snapshot views, WORM and version folders, the NFS exports file, the fan watchdog's heartbeat
file (its own contract), the secrets file, the restic location backup_migration made
(zettnas-restic), the family calendar's DAV identity, the RAG schema's embedding id, the WebDAV
fallback secret (tokens signed with it), the recovery-code hash prefix, the restic host id, VM serial
sockets in saved VM definitions, the apps' .zettnas-secrets.json, the backup versions and dump names,
and outside the app: the hardware runner's label (set on the runner) and the deployed health worker's
names.
"""

import os
from typing import overload

REMOVE_IN = "2.2.0"
ENV_PREFIX = "KIBOTO_"
OLD_ENV_PREFIX = "ZETTNAS_"
OLD_IMAGE_REPO = "fr0styx/zettnas-toolkit"  # CI also publishes and signs every image under this name
OLD_GITHUB_REPO = "fr0styx/zettnas-toolkit"  # images signed before the repo's rename carry this identity
OLD_MANAGED_LABEL = "com.zettnas.managed"  # new containers carry both (an older version, after a
OLD_APP_LABEL = "com.zettnas.app"  # rollback, knows only these)
OLD_APP_NETWORK_PREFIX = "zettnas-app-"  # an app's network made before keeps its name
OLD_FOLLOW_TAG_LABEL = "zettnas.image.follow-tag"
OLD_AI_PACK = "zettnas-ai"  # an AI pack made before keeps its container, models folder and model names
OLD_AI_PACK_LABEL = "zettnas.ai-pack"
OLD_AI_PACK_MODELS = ("zettnas-chat", "zettnas-embed")
OLD_SAMBA = "zettnas-samba"  # sidecars made before are found (Samba) or replaced (SFTP, the updater)
OLD_SFTP = "zettnas-sftp"
OLD_SELF_UPDATER = "zettnas-self-updater"
OLD_APP_CONTAINER = "zettnas-toolkit"  # the app's own container on installs made before
OLD_APP_CONTAINER_NAMES = ("zettnas-toolkit", "zettnas", "zettnas_toolkit")
OLD_NAME_START = "zettnas"  # Kiboto's own containers made before (the app, sidecars, model servers)
OLD_ROLLBACK_REPO = "zettnas-toolkit-rollback"  # rollback images tagged before keep their tag
OLD_FAN_HEARTBEAT = "zettnas-fan-heartbeat.json"  # a fan watchdog from before reads this name (written too)
OLD_HOST_APPDATA = "/mnt/user/appdata/zettnas-toolkit"  # Unraid's appdata folder on installs made before
OLD_MODEL_SERVERS = ("zettnas-ollama", "zettnas-ovms")
OLD_SESSION_COOKIE = "zettnas_session"  # browsers signed in before the rebrand still send it
OLD_CANARY_NAME = "!ZettNAS-guard-file.docx"  # the ransomware guard's file before the rebrand
OLD_NAS_NAME = "zettnas"  # a saved name from before becomes kiboto; zettnas.local no longer answers
OLD_NAME_CONTAINER = "zettnas-name"  # the name responder's container before the rebrand: replaced
OLD_PART_SUFFIX = ".zettnas-part"  # a half-copied file left by a transfer before the rebrand: swept
OLD_STAGE_INFIX = ".zettnas-stage-"  # a move's staging folder from before the rebrand: swept
OLD_STAGE_NAME = "zettnas"  # the same staging folder's name part, for the sweep's pattern
OLD_UPLOAD_INFIX = ".zettnas_"  # an upload's part file from before the rebrand: swept
OLD_EXPORTS_NAME = "zettnas.exports"  # NFS: the file from before, removed once the new one is written
OLD_DATA_MARKER = ".zettnas-data-id"  # the data folder's mark: renamed
OLD_ENCRYPTED_HIDDEN = ".zettnas-encrypted"  # an encrypted folder's files in its share: renamed
OLD_APP_MADE_FILE = ".zettnas-secrets.json"  # an app's generated passwords: renamed
OLD_VERSIONS_DIR = ".zettnas-versions"  # a copy job's replaced files at its destination: renamed
OLD_DUMP_NAMES = (".zettnas-dump.sql", ".zettnas-dump.archive")  # an app's database dump: removed
OLD_MANIFEST_NAME = "zettnas-backup.json"  # inside a settings backup made before
OLD_ENCRYPTED_MAGIC = b"ZETTBAK2"  # a settings backup made before starts with it (also its AAD)
OLD_SETTINGS_EXT = ".zettbak"  # a settings backup made before
OLD_EXPORT_PREFIX = "zettnas_backup_"  # a settings backup job's files made before: kept by count
OLD_OFFSITE_SETTINGS_FILE = "kiboto-settings.zettbak"  # settings in an off-site version made before
OLD_SNAPSHOT_VIEWS = "zettnas-snapshot-views"  # a temporary folder of read-only snapshot views
OLD_REPL_PREFIX = "zettnas-repl-"  # a replication job's snapshots on both sides: renamed before a run
OLD_REPL_DIR = ".zettnas-repl"  # btrfs: the folder of a job's local snapshots: renamed
OLD_LEXICAL_MODEL = "zett_lexical_384d"  # the search index's own embedding id: renamed in its rows
OLD_UNIFIED_MODEL = "zettnas-unified-384-v2"  # the same, an older default for chunks
OLD_VM_SOCK_DIR = "zettnas-vms"  # /tmp/<it>/<vm>/serial.sock: a VM started before
OLD_KDF_SALT = b"zettnas-data-key-v1"  # the AI databases' key salt: re-encrypted once under the new one
OLD_CREDENTIAL_NAME = "zettnas-data-key"  # systemd credential holding the data key, read if the new one is not there
OLD_BOX_KEY_START = b"zettnas-secret-box-v1:"  # sealed values ("enc1:"): re-sealed once as "enc2:"
OLD_BOX_AAD = b"zettnas:mfa_secret:v1"
OLD_RECOVERY_START = "zettnas:recovery:"  # recovery codes made before: accepted until used or made again
OLD_BACKUP_TAG = "zettnas"  # the restic tag on off-site file backups made before: retagged once per repo
OLD_RESTIC_HOST_START = "zettnas-"  # the restic host of backups made before: kept hex, moved once per repo
OLD_LOG_FILE = "zettnas.log"  # the log file and its rotations carry on under the new name


def managed_labels() -> dict[str, str]:
    """The labels that mark a container or network as Kiboto's: the new one and, until 2.2, the old."""
    from backend import product

    return {product.MANAGED_LABEL: "1", OLD_MANAGED_LABEL: "1"}


def is_managed(labels: dict | None) -> bool:
    from backend import product

    labels = labels or {}
    return labels.get(product.MANAGED_LABEL) == "1" or labels.get(OLD_MANAGED_LABEL) == "1"


def follow_tag_labels() -> dict[str, str]:
    from backend import product

    return {product.FOLLOW_TAG_LABEL: "1", OLD_FOLLOW_TAG_LABEL: "1"}


def follows_tag(labels: dict | None) -> bool:
    from backend import product

    labels = labels or {}
    return labels.get(product.FOLLOW_TAG_LABEL) == "1" or labels.get(OLD_FOLLOW_TAG_LABEL) == "1"


def made_before(name: str | None) -> bool:
    """A container Kiboto made before the rebrand: the app itself, a sidecar or a model server."""
    return str(name or "").lstrip("/").lower().startswith(OLD_NAME_START)


def app_container_names() -> tuple[str, ...]:
    """Kiboto's own container: kiboto, or a name from before the rebrand."""
    from backend import product

    return (product.CONTAINER, *OLD_APP_CONTAINER_NAMES)


def is_app_container(name: str | None) -> bool:
    return str(name or "").lstrip("/").lower() in app_container_names()


def old_env_name(name: str) -> str | None:
    """ZETTNAS_X for KIBOTO_X; None for any other name."""
    return OLD_ENV_PREFIX + name[len(ENV_PREFIX) :] if name.startswith(ENV_PREFIX) else None


@overload
def getenv(name: str) -> str | None: ...
@overload
def getenv(name: str, default: str) -> str: ...
def getenv(name: str, default: str | None = None) -> str | None:
    """os.environ.get for a KIBOTO_ variable that falls back to its ZETTNAS_ name; the new name wins."""
    if name in os.environ:
        return os.environ[name]
    old = old_env_name(name)
    if old and old in os.environ:
        return os.environ[old]
    return default


OLD_APP_PLACEHOLDER = "{{zettnas}}"  # app definitions saved before: {{kiboto}}
OLD_APP_NETWORK_FIELD = "join_zettnas_network"  # app definitions saved before: join_kiboto_network


def renamed_app(value):
    """An app definition (any JSON value) with the placeholder and key from before in Kiboto's names."""
    if isinstance(value, dict):
        return {("join_kiboto_network" if k == OLD_APP_NETWORK_FIELD else k): renamed_app(v) for k, v in value.items()}
    if isinstance(value, list):
        return [renamed_app(v) for v in value]
    if isinstance(value, str):
        return value.replace(OLD_APP_PLACEHOLDER, "{{kiboto}}")
    return value


def rename_app_files(data_dir: str, write_json) -> int:
    """Sideloaded apps and cached catalogs saved before the rebrand, renamed where they are stored,
    with `write_json` (fsutil.atomic_write_json: this module imports nothing of Kiboto's, since
    settings imports it). Returns how many files changed."""
    import glob
    import json

    changed = 0
    paths = [
        os.path.join(data_dir, "sideloaded_apps.json"),
        *glob.glob(os.path.join(data_dir, "catalog_cache", "*.json")),
    ]
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        new = renamed_app(data)
        if new != data:
            write_json(path, new)
            changed += 1
    return changed


def rename_at_start(data_dir: str, write_json) -> None:
    """The one-time renames of names stored before the rebrand; each finds nothing once done."""
    rename_app_files(data_dir, write_json)


def existing(folder: str, name: str, old_name: str) -> str:
    """`folder/name`, or `folder/old_name` while only the old one is there (not renamed yet)."""
    new = os.path.join(folder, name)
    old = os.path.join(folder, old_name)
    return old if not os.path.lexists(new) and os.path.lexists(old) else new


def moved(folder: str, name: str, old_name: str) -> str:
    """`folder/name`, renaming a file or folder of the old name to it first when only that is there.
    Where the rename is refused, the old one is used where it is."""
    new = os.path.join(folder, name)
    old = os.path.join(folder, old_name)
    if not os.path.lexists(new) and os.path.lexists(old):
        try:
            os.rename(old, new)
        except OSError:
            return old
    return new


def is_old_settings_export(name: str) -> bool:
    return name.startswith(OLD_EXPORT_PREFIX) and name.endswith(OLD_SETTINGS_EXT)


def rename_index_models(conn, lexical: str, unified: str) -> int:
    """The search index's model ids from before the rebrand, renamed in its rows; the partial index
    whose condition named the old id is dropped, so the schema makes it again with the new one.
    Tables are looked up first (the index may be SQLCipher, whose errors are its own). Returns
    how many rows changed."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    changed = 0
    for table in ("indexed_files", "document_chunks"):
        if table not in tables:
            continue
        for old, new in ((OLD_LEXICAL_MODEL, lexical), (OLD_UNIFIED_MODEL, unified)):
            cur = conn.execute(f"UPDATE {table} SET embedding_model = ? WHERE embedding_model = ?", (new, old))  # noqa: S608
            changed += max(cur.rowcount, 0)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'idx_files_fallback_vectors'"
    ).fetchone()
    if row and OLD_LEXICAL_MODEL in str(row[0] or ""):
        conn.execute("DROP INDEX idx_files_fallback_vectors")
    return changed
