"""Kiboto OS: the udev rules of the release (packaging/99-kiboto-ups.rules), put in place by the host
door at each start so Kiboto's own user may use a UPS on a USB cable without root (ADR 0006). A
changed rule is applied at once to the devices that are there."""

import os
import subprocess
from collections.abc import Callable

from backend.config import logger

UDEV_DIR = "/etc/udev/rules.d"
RULES = ("99-kiboto-ups.rules",)


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, capture_output=True, timeout=60, check=False)  # noqa: S603
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("[Door] %s did not run: %s", cmd[0], e)


def keep_current(rel: str, udev_dir: str = "", run: Callable[[list[str]], object] | None = None) -> list[str]:
    """Writes the release's rules where they differ; returns the ones that changed."""
    udev_dir = udev_dir or UDEV_DIR
    if not os.path.isdir(udev_dir):
        return []
    changed = []
    for name in RULES:
        try:
            with open(os.path.join(rel, "packaging", name), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue  # a release from before this rule
        path = os.path.join(udev_dir, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                if f.read() == text:
                    continue
        with open(path + ".new", "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path + ".new", 0o644)
        os.replace(path + ".new", path)
        changed.append(name)
    if changed:
        runner = run or _run
        runner(["udevadm", "control", "--reload"])
        runner(["udevadm", "trigger", "--subsystem-match=hidraw"])
        logger.info("[Door] udev rules written: %s", ", ".join(changed))
    return changed
