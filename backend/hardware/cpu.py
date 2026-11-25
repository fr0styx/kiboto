import glob
import os
import time

from backend.config import HOST_PROC, HOST_SYS
from backend.state import Z_STATE


def read_cpu_util():
    try:
        with open(os.path.join(HOST_PROC, "stat")) as f:
            parts = f.readline().split()[1:]
        vals = list(map(int, parts))
        idle = vals[3]
        total = sum(vals[:8]) if len(vals) >= 8 else sum(vals)
        d_idle = idle - Z_STATE.prev["idle"]
        d_total = total - Z_STATE.prev["total"]
        Z_STATE.prev["idle"], Z_STATE.prev["total"] = idle, total
        if d_total <= 0:
            return 0
        return round(100 * (1 - d_idle / d_total))
    except Exception:
        return 0


def kernel_cooled(h: str) -> bool:
    """The kernel's thermal governor drives this fan: its device is also a thermal cooling device
    (a pwm-fan with cooling-levels, as on the Zettlab D4). Writing its pwm would fight the kernel,
    which writes its own level back, so Kiboto only reads such a fan (#68)."""
    link = os.path.join(h, "device")
    if not os.path.exists(link):
        return False
    dev = os.path.realpath(link)
    for cd in glob.glob(os.path.join(HOST_SYS, "class/thermal/cooling_device*")):
        cd_link = os.path.join(cd, "device")
        if os.path.exists(cd_link) and os.path.realpath(cd_link) == dev:
            return True
    return False


def _find_hwmon():
    """The hwmon device whose fans Kiboto drives; None when there is none it may write."""
    if Z_STATE.cached_hwmon and os.path.exists(Z_STATE.cached_hwmon):
        return Z_STATE.cached_hwmon
    for h in sorted(glob.glob(os.path.join(HOST_SYS, "class/hwmon/hwmon*"))):
        try:
            with open(os.path.join(h, "name")) as f:
                n = f.read().strip()
        except Exception:
            continue
        if n in ("zettlab_d8_fans", "zettos_pwm_fan", "nct6775", "it87") and not kernel_cooled(h):
            Z_STATE.cached_hwmon = h
            return h
    for h in sorted(glob.glob(os.path.join(HOST_SYS, "class/hwmon/hwmon*"))):
        if glob.glob(os.path.join(h, "pwm*")) and not kernel_cooled(h):
            Z_STATE.cached_hwmon = h
            return h
    return None


def read_cpu_temp():
    if Z_STATE.cached_cpu_temp_path and os.path.exists(Z_STATE.cached_cpu_temp_path):
        try:
            val = int(open(Z_STATE.cached_cpu_temp_path).read().strip() or 0) / 1000  # noqa: SIM115
            if val > 0:
                return round(val)
        except Exception:
            Z_STATE.cached_cpu_temp_path = None

    # 1. Hardware Monitor Drivers (coretemp, k10temp, zenpower, cpu_thermal)
    for h in sorted(glob.glob(os.path.join(HOST_SYS, "class/hwmon/hwmon*"))):
        try:
            name = open(os.path.join(h, "name")).read().strip()  # noqa: SIM115
            if name in ("coretemp", "k10temp", "zenpower", "cpu_thermal"):
                for t in sorted(glob.glob(os.path.join(h, "temp*_input"))):
                    val = int(open(t).read().strip() or 0) / 1000  # noqa: SIM115
                    if val > 0:
                        Z_STATE.cached_cpu_temp_path = t
                        return round(val)
        except Exception:
            continue

    # 2. ACPI / Linux thermal zones (/sys/class/thermal/thermal_zone*)
    for base in (HOST_SYS, "/sys", "/host/sys"):
        if not base or not os.path.exists(base):
            continue
        for tz in sorted(glob.glob(os.path.join(base, "class/thermal/thermal_zone*"))):
            try:
                temp_file = os.path.join(tz, "temp")
                type_file = os.path.join(tz, "type")
                if os.path.exists(temp_file):
                    tz_type = open(type_file).read().strip().lower() if os.path.exists(type_file) else ""  # noqa: SIM115
                    if not tz_type or any(k in tz_type for k in ("acpi", "cpu", "x86_pkg", "soc", "package")):
                        val = int(open(temp_file).read().strip() or 0)  # noqa: SIM115
                        if val > 1000:
                            val /= 1000
                        if val > 0:
                            Z_STATE.cached_cpu_temp_path = temp_file
                            return round(val)
            except Exception:
                continue

    return None


# The processor's own limit (owner, 25 Nov 2026): its sensor chip says how hot it may run
# (coretemp's tempN_crit or tempN_max: 110 °C for a Core Ultra 5 125H, 100 °C for many others).
LIMIT_RECHECK_SECS = 3600
_limit = {"at": 0.0, "value": None}


def read_cpu_limit() -> float | None:
    """The highest temperature the processor reports it is made for, in °C, from the sensor chip
    that gives its temperature; None when it reports none, or something implausible (85-125 °C)."""
    now = time.time()
    if now - _limit["at"] < LIMIT_RECHECK_SECS:
        return _limit["value"]
    value = None
    if read_cpu_temp() is not None and Z_STATE.cached_cpu_temp_path:
        base = Z_STATE.cached_cpu_temp_path.rsplit("_input", 1)[0]
        for suffix in ("_crit", "_max"):
            try:
                with open(base + suffix) as f:
                    found = int(f.read().strip() or 0) / 1000
            except (OSError, ValueError):
                continue
            if 85 <= found <= 125:
                value = found
                break
    _limit.update(at=now, value=value)
    return value
