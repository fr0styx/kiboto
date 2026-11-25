"""What the test setup refuses to run on the machine the tests run on (conftest._never_the_real_machine)."""

import os
import tempfile

POWER_COMMANDS = {"poweroff", "reboot", "halt", "shutdown", "powerdown", "kexec"}


def powers_off(argv) -> bool:
    """Whether a command line would switch off or restart the machine it runs on."""
    import shlex

    try:
        parts = shlex.split(argv) if isinstance(argv, str) else [str(a) for a in argv]
    except (TypeError, ValueError):
        return False
    if not parts:
        return False
    name = os.path.basename(parts[0])
    if name in POWER_COMMANDS:
        return not os.path.realpath(parts[0]).startswith(os.path.realpath(tempfile.gettempdir()) + os.sep)
    if name in ("systemctl", "loginctl", "busctl"):
        return any(p in POWER_COMMANDS or p in ("kexec", "suspend", "hibernate") for p in parts[1:])
    return False
