"""The pool record is in the data folder, which the web process can write, and bringing pools back
runs as root in the host door (ADR 0006, CodeQL py/command-line-injection on pools_at_boot)."""

from backend.hardware.pal import pool_registry as reg
from backend.services import pools_at_boot


def _row(**kw):
    row = {
        "name": "tank",
        "fs_type": "btrfs",
        "profile": "raid1",
        "uuid": "0d078745-c080-4577-bf15-4f8cbbde3dae",
        "members": ["/dev/sdb", "/dev/sdc"],
        "mountpoint": "/mnt/storage/tank",
        "options": "compress=zstd:1,noatime,space_cache=v2",
    }
    row.update(kw)
    return row


def test_kibotos_own_records_pass():
    assert reg.unsafe(_row()) == ""
    assert reg.unsafe(_row(fs_type="zfs", uuid="1234567890123456789", mountpoint="")) == ""
    assert reg.unsafe(_row(fs_type="ext4", options="")) == ""
    assert reg.unsafe(_row(fs_type="xfs", uuid="ABCD-1234", mountpoint="/srv/media")) == ""


def test_a_changed_record_is_refused():
    bad = [
        _row(name="-o"),
        _row(name="tank;reboot"),
        _row(uuid="-d /tmp"),
        _row(uuid="x" * 70),
        _row(uuid="ab cd"),
        _row(mountpoint="/etc"),
        _row(mountpoint="/usr/bin"),
        _row(mountpoint="/var/lib/kiboto"),
        _row(mountpoint="/"),
        _row(mountpoint="/mnt"),
        _row(mountpoint="/mnt/storage/../../etc"),
        _row(mountpoint="relative/path"),
        _row(options="suid"),
        _row(options="noatime,dev"),
        _row(options="noatime,exec"),
        _row(options="uid=0,x-mount.mkdir"),
        _row(options="compress=zstd:1 -o remount"),
    ]
    for row in bad:
        assert reg.unsafe(row), row


def test_nothing_of_a_changed_record_reaches_a_command():
    ran = []

    def run(cmd):
        ran.append(cmd)
        return 0, "", ""

    why = reg.bring_back(_row(mountpoint="/etc"), run)
    assert why.startswith("its record was changed outside Kiboto") and ran == []
    assert reg.is_there(_row(name="-o"), run) is False and ran == []


def test_the_boot_runner_starts_only_its_own_programs():
    assert pools_at_boot._run(["sh", "-c", "id"])[0] == 126
    assert pools_at_boot._run([])[0] == 126
    code, _out, _err = pools_at_boot._run(["findmnt", "--version"])
    assert code in (0, 127)  # there, or not installed in this image: either way it was allowed
