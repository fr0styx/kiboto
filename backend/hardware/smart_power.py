"""Whether a drive is asleep, from one `smartctl -n standby` run (NARC-1).

smartctl's exit bit 1 (value 2) means "device open failed, device did not return an IDENTIFY
DEVICE structure, or device is in a low-power mode". Only the last prints a standby or sleep
message, so the message decides: a drive that couldn't be opened or didn't identify itself is
"unreachable", never "standby". It may be failing, unplugged or behind the wrong bridge type,
and it must not pass for a sleeping one.
"""

import os

STANDBY_WORDS = ("DEVICE IS IN STANDBY", "DEVICE IS IN SLEEP", "STANDBY MODE", "SLEEP MODE")
VIRTUAL_NAMES = ("vd", "xvd")  # virtio and Xen block devices
VIRTUAL_MODELS = ("QEMU", "VMWARE", "VBOX", "VIRTUAL DISK", "VIRTUAL HD")


def virtual_disk(name: str, sys_root: str = "/sys") -> bool:
    """Whether `name` is a virtual machine's disk (virtio, Xen, or a QEMU, VMware, VirtualBox or
    Hyper-V model). It has no SMART and never spins down; asked with -d sat, smartctl answers
    "Device is in SLEEP mode" for it, and every folder on it passed for one on a sleeping disk."""
    if name.startswith(VIRTUAL_NAMES):
        return True
    said = []
    for field in ("vendor", "model"):
        try:
            with open(os.path.join(sys_root, "block", name, "device", field), encoding="utf-8", errors="replace") as f:
                said.append(f.read())
        except OSError:
            continue
    text = " ".join(said).upper()
    return any(word in text for word in VIRTUAL_MODELS)


def smartctl_power(returncode: int, output: str) -> str:
    """ "standby", "unreachable" or "active"."""
    out = (output or "").upper()
    if any(w in out for w in STANDBY_WORDS):
        return "standby"
    if int(returncode or 0) & 2:
        return "unreachable"
    return "active"


def is_standby(returncode: int, output: str) -> bool:
    return smartctl_power(returncode, output) == "standby"
