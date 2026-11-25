"""The Zettlab D4 (RK3588, ARM) as a tester reported it (#68, #69): the adapter name the docs give,
fans the kernel drives, a pool counted twice, and its Mali GPU and Rockchip NPU."""

import os

from backend.hardware import cpu, fans, host_telemetry
from backend.hardware.pal import detect, generic_linux
from backend.hardware.pal.base import PlatformType
from backend.state import Z_STATE


def _write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def _link(target, link):
    os.makedirs(os.path.dirname(link), exist_ok=True)
    os.symlink(target, link)


# --- #69 ---------------------------------------------------------------------------------------


def test_generic_is_the_generic_linux_adapter(monkeypatch):
    values = {"observer_adapter": "generic", "pal_mode": "", "platform": ""}
    monkeypatch.setattr(detect._settings, "current", lambda k: values[k])
    assert detect.StoragePlatformDetector.detect() == PlatformType.GENERIC_LINUX


def test_an_unknown_adapter_is_said_once(monkeypatch, caplog):
    detect._WARNED.clear()
    for _ in range(3):
        detect._warn_unknown("genric")
    said = [r for r in caplog.records if "genric" in r.getMessage()]
    assert len(said) == 1 and "no known adapter" in said[0].getMessage()


# --- fans ---------------------------------------------------------------------------------------


def _d4_sys(root, cooled=True):
    """Two pwm-fan hwmon devices, each also a thermal cooling device when `cooled`."""
    for n, (rpm, plat) in enumerate(((2500, "pwm-fan1"), (3000, "pwm-fan2"))):
        dev = root / "devices" / "platform" / plat
        dev.mkdir(parents=True)
        h = root / "class" / "hwmon" / f"hwmon{8 + n}"
        h.mkdir(parents=True)
        _write(str(h / "name"), "pwmfan\n")
        _write(str(h / "fan1_input"), f"{rpm}\n")
        _write(str(h / "pwm1"), "152\n")
        os.symlink(os.path.relpath(dev, h), h / "device")
        if cooled:
            cd = root / "class" / "thermal" / f"cooling_device{n}"
            cd.mkdir(parents=True)
            _write(str(cd / "type"), "pwm-fan\n")
            os.symlink(os.path.relpath(dev, cd), cd / "device")


def test_fans_the_kernel_drives_are_only_read(tmp_path, monkeypatch):
    _d4_sys(tmp_path)
    monkeypatch.setattr(cpu, "HOST_SYS", str(tmp_path))
    monkeypatch.setattr(fans, "HOST_SYS", str(tmp_path))
    monkeypatch.setattr(Z_STATE, "cached_hwmon", None)
    monkeypatch.setattr(fans, "get_mmio_fan_controller", lambda: None)
    assert cpu.kernel_cooled(str(tmp_path / "class" / "hwmon" / "hwmon8"))
    assert cpu._find_hwmon() is None  # nothing Kiboto writes
    assert fans.read_fans() == [2500, 3000]  # both fans, read
    assert Z_STATE.fan_driver_mode == "none"


def test_a_fan_no_cooling_device_claims_is_still_driven(tmp_path, monkeypatch):
    _d4_sys(tmp_path, cooled=False)
    monkeypatch.setattr(cpu, "HOST_SYS", str(tmp_path))
    monkeypatch.setattr(Z_STATE, "cached_hwmon", None)
    assert cpu._find_hwmon() == str(tmp_path / "class" / "hwmon" / "hwmon8")


# --- pools --------------------------------------------------------------------------------------


def test_the_pool_folder_is_found_on_its_device():
    mounts = [
        {"device": "/dev/bcache0", "mountpoint": "/zettlab/data", "fstype": "btrfs"},
        {"device": "/dev/bcache0", "mountpoint": "/mnt/storage", "fstype": "btrfs"},
        {"device": "/dev/sda1", "mountpoint": "/mnt", "fstype": "ext4"},
    ]
    assert generic_linux._mount_device(mounts, "/mnt/storage") == "/dev/bcache0"
    assert generic_linux._mount_device(mounts, "/mnt/storage/photos") == "/dev/bcache0"
    assert generic_linux._mount_device(mounts, "/mnt/other") == "/dev/sda1"
    assert generic_linux._mount_device(mounts, "/srv") == ""


# --- AI chips -----------------------------------------------------------------------------------


def _drm(root, card, driver):
    d = root / "sys" / "devices" / "platform" / f"{card}-dev"
    (root / "sys" / "bus" / "platform" / "drivers" / driver).mkdir(parents=True, exist_ok=True)
    d.mkdir(parents=True)
    os.symlink(os.path.relpath(root / "sys" / "bus" / "platform" / "drivers" / driver, d), d / "driver")
    c = root / "sys" / "class" / "drm" / card
    c.mkdir(parents=True)
    os.symlink(os.path.relpath(d, c), c / "device")


def test_a_rockchip_board_shows_its_mali_and_npu_as_not_used(tmp_path, monkeypatch):
    _drm(tmp_path, "card0", "rockchip-drm")
    _drm(tmp_path, "card1", "RKNPU")
    (tmp_path / "sys" / "class" / "drm" / "card0-DSI-1").mkdir()
    _write(str(tmp_path / "dev" / "mali0"))
    _write(str(tmp_path / "dev" / "dri" / "renderD128"))
    monkeypatch.setattr(host_telemetry, "HOST_SYS", str(tmp_path / "sys"))
    monkeypatch.setattr(host_telemetry, "HOST_DEV", str(tmp_path / "dev"))
    monkeypatch.setattr(host_telemetry, "_GPU_CACHE", {})
    monkeypatch.setattr(host_telemetry, "_NPU_CACHE", {})
    gpu = host_telemetry.get_gpu_telemetry()
    assert gpu["vendor"] == "Arm" and gpu["short_name"] == "Mali GPU"
    assert gpu["present"] and gpu["usable"] is False and gpu["ready"] is False
    assert "Arc" not in gpu["model"]
    npu = host_telemetry.get_npu_telemetry()
    assert npu["vendor"] == "Rockchip" and npu["present"] and npu["usable"] is False
    assert npu["render_node"] == "/dev/dri/card1"


def test_an_intel_gpu_keeps_its_name(tmp_path, monkeypatch):
    c = tmp_path / "sys" / "class" / "drm" / "card0" / "device"
    _write(str(c / "vendor"), "0x8086\n")
    _write(str(c / "device"), "0x7d55\n")
    _write(str(tmp_path / "dev" / "dri" / "renderD128"))
    monkeypatch.setattr(host_telemetry, "HOST_SYS", str(tmp_path / "sys"))
    monkeypatch.setattr(host_telemetry, "HOST_DEV", str(tmp_path / "dev"))
    monkeypatch.setattr(host_telemetry, "_GPU_CACHE", {})
    gpu = host_telemetry.get_gpu_telemetry()
    assert gpu["vendor"] == "Intel" and gpu["short_name"] == "Intel GPU" and gpu["usable"] is True
