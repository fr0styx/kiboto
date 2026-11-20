"""
Kiboto - DMTF Redfish Scalable Platforms Management API (Phase 3)
Provides high-performance, DMTF-compliant RESTful telemetry (< 2ms response time)
served directly from in-memory system state without blocking disk or subprocess I/O.
"""

import os
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from backend import __version__
from backend.auth import require_scope
from backend.config import HOST_SYS
from backend.state import Z_STATE


def _redfish_on() -> None:
    """Redfish answers only where an administrator turned it on (SET-01)."""
    from backend.services import redfish_access

    if not redfish_access.enabled():
        raise HTTPException(status_code=404, detail="Redfish is turned off on this NAS.")


# every route, the service root included: turned on, and a signed-in account that may read the system
router = APIRouter(
    tags=["Redfish"],
    dependencies=[Depends(_redfish_on), Depends(require_scope("system:view", "storage:read"))],
)

REDFISH_HEADERS = {
    "OData-Version": "4.0",
    "Content-Type": "application/json;charset=utf-8",
}


def _get_stats() -> dict[str, Any]:
    return getattr(Z_STATE, "cached_stats", {}) or {}


# --- what a drive's record really holds --------------------------------------------------------
# The live record of a drive has dev, temp, health, risk and standby. These pages once read
# size_bytes and smart_fail, which it never had: every drive was 0 bytes and "OK", a failing one too.
_SIZES: dict[str, int] = {}


def _sys_block(dev: str, leaf: str) -> str | None:
    """A value the kernel keeps for a drive (/sys/block): read from memory, so no drive is woken."""
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", dev or ""):
        return None
    try:
        # the kernel's own name for the drive, never the string a request brought: ".." matched the
        # pattern above, and a list of drives has no such entry (CodeQL py/path-injection)
        name = next((n for n in os.listdir(os.path.join(HOST_SYS, "block")) if n == dev), None)
        if name is None:
            return None
        with open(os.path.join(HOST_SYS, "block", name, leaf), encoding="ascii") as f:
            return f.read().strip()
    except OSError:
        return None


def _capacity(d: dict[str, Any]) -> int | None:
    """The drive's size in bytes, or None when it is not known (never 0 for a drive that is there)."""
    given = d.get("size_bytes")
    if isinstance(given, (int, float)) and not isinstance(given, bool) and given > 0:
        return int(given)
    dev = str(d.get("dev") or d.get("name") or "")
    if dev not in _SIZES:
        sectors = _sys_block(dev, "size")
        if not (sectors and sectors.isdigit() and int(sectors) > 0):
            return None
        _SIZES[dev] = int(sectors) * 512  # the kernel counts in 512-byte sectors whatever the drive's own size
    return _SIZES[dev]


def _drive_health(d: dict[str, Any]) -> str | None:
    """Redfish's word for the drive's health: Critical, Warning, OK, or None while SMART has not answered."""
    word = str(d.get("health") or "").lower()
    if d.get("smart_fail") or word in ("crit", "critical", "fail", "failed", "failing"):
        return "Critical"
    if word in ("warn", "warning"):
        return "Warning"
    if word == "unknown":
        return None
    return "OK"  # ok, or asleep: a sleeping drive keeps its last word


def _media_type(d: dict[str, Any], dev: str) -> str:
    if "nvme" in dev.lower() or d.get("is_nvme"):
        return "SSD"
    return "SSD" if _sys_block(dev, "queue/rotational") == "0" else "HDD"


def _system_uuid() -> str:
    from backend.services import redfish_access

    return redfish_access.system_uuid()


def _made_by(stats: dict[str, Any]) -> tuple[str | None, str | None, str]:
    """(manufacturer, model, name) of the machine Kiboto runs on. A Zettlab chassis says so; any
    other machine is named by its own board, not called a Zettlab."""
    from backend.hardware.storage import get_chassis_friendly_name

    slug = str(stats.get("chassis") or "")
    label = str(stats.get("chassis_label") or "") or (get_chassis_friendly_name(slug) if slug else "")
    if label.lower().startswith("zettlab"):
        return "Zettlab", slug.upper(), label
    sent = stats.get("motherboard")
    board: dict[str, Any] = sent if isinstance(sent, dict) else {}
    vendor = str(board.get("vendor") or "") or None
    model = str(board.get("product") or board.get("board") or "") or None
    return vendor, model, " ".join(x for x in (vendor, model) if x) or "Kiboto NAS"


def _worst(healths: list[str | None]) -> str:
    """The roll-up for the whole array: its worst drive."""
    return "Critical" if "Critical" in healths else "Warning" if "Warning" in healths else "OK"


@router.get("", include_in_schema=True)
@router.get("/", include_in_schema=True)
def get_service_root():
    """Redfish Service Root (/redfish/v1/)."""
    return {
        "@odata.context": "/redfish/v1/$metadata#ServiceRoot.ServiceRoot",
        "@odata.id": "/redfish/v1",
        "@odata.type": "#ServiceRoot.v1_15_0.ServiceRoot",
        "Id": "RootService",
        "Name": "Kiboto Redfish Service Root",
        "RedfishVersion": "1.15.0",
        "UUID": _system_uuid(),
        "Product": "Kiboto Appliance Management Suite",
        "Vendor": "Zettlab",
        "SoftwareVersion": __version__,
        "Systems": {"@odata.id": "/redfish/v1/Systems"},
        "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
        "Storage": {"@odata.id": "/redfish/v1/Storage"},
        "Oem": {
            "ZettLab": {
                "ToolkitVersion": __version__,
                "Architecture": "Universal Hardware & OS Agnostic",
            }
        },
    }


@router.get("/Chassis")
@router.get("/Chassis/")
def list_chassis():
    """Redfish Chassis Collection."""
    return {
        "@odata.context": "/redfish/v1/$metadata#ChassisCollection.ChassisCollection",
        "@odata.id": "/redfish/v1/Chassis",
        "@odata.type": "#ChassisCollection.ChassisCollection",
        "Name": "Chassis Collection",
        "Members@odata.count": 1,
        "Members": [{"@odata.id": "/redfish/v1/Chassis/1"}],
    }


@router.get("/Chassis/1")
@router.get("/Chassis/1/")
def get_chassis_detail():
    """Redfish Chassis/1 Detail."""
    stats = _get_stats()
    maker, model, model_name = _made_by(stats)

    return {
        "@odata.context": "/redfish/v1/$metadata#Chassis.Chassis",
        "@odata.id": "/redfish/v1/Chassis/1",
        "@odata.type": "#Chassis.v1_22_0.Chassis",
        "Id": "1",
        "Name": model_name,
        # a NAS on a desk or a shelf; the "u" in a model name (D6 Ultra) never meant a rack unit
        "ChassisType": "StandAlone",
        "Manufacturer": maker,
        "Model": model,
        "Status": {
            "State": "Enabled",
            "Health": _worst([_drive_health(d) for d in stats.get("disks") or []]),
        },
        "PowerState": "On",
        "Thermal": {"@odata.id": "/redfish/v1/Chassis/1/Thermal"},
        "Links": {
            "ComputerSystems": [{"@odata.id": "/redfish/v1/Systems/1"}],
            "Storage": [{"@odata.id": "/redfish/v1/Storage/1"}],
        },
    }


@router.get("/Chassis/1/Thermal")
@router.get("/Chassis/1/Thermal/")
def get_thermal_telemetry():
    """Redfish Chassis/1/Thermal: Fan RPMs and Temperature Sensors."""
    stats = _get_stats()

    # Temperature Sensors
    temps = []

    # CPU Temperature
    cpu = stats.get("cpu", {})
    cpu_temp = cpu.get("temp")
    if cpu_temp is not None:
        temps.append(
            {
                "@odata.id": "/redfish/v1/Chassis/1/Thermal#/Temperatures/CPU",
                "MemberId": "CPU",
                "Name": "CPU Thermal Package",
                "ReadingCelsius": float(cpu_temp),
                "UpperThresholdCritical": 85.0,
                "UpperThresholdFatal": 100.0,
                "Status": {"State": "Enabled", "Health": "OK" if cpu_temp < 80 else "Critical"},
            }
        )

    # Disks & NVMe Temperatures
    for d in stats.get("disks", []):
        dev = d.get("dev") or d.get("name", "disk")
        temp = d.get("temp")
        is_standby = d.get("standby", False)
        is_nvme = "nvme" in dev.lower()
        crit_thresh = 70.0 if is_nvme else 55.0

        temps.append(
            {
                "@odata.id": f"/redfish/v1/Chassis/1/Thermal#/Temperatures/{dev}",
                "MemberId": dev,
                "Name": f"Disk Sensor {dev}",
                "ReadingCelsius": float(temp) if temp is not None else None,
                "UpperThresholdCritical": crit_thresh,
                "Status": {
                    "State": "StandbyOffline" if is_standby else "Enabled",
                    "Health": "OK" if (temp is None or temp < crit_thresh) else "Warning",
                },
            }
        )

    # Fans
    fans_data = []
    fans = stats.get("fans", [])
    for idx, rpm in enumerate(fans):
        fans_data.append(
            {
                "@odata.id": f"/redfish/v1/Chassis/1/Thermal#/Fans/{idx + 1}",
                "MemberId": f"Fan{idx + 1}",
                "Name": f"Chassis Fan {idx + 1}",
                "Reading": int(rpm),
                "ReadingUnits": "RPM",
                "Status": {"State": "Enabled", "Health": "OK"},
            }
        )

    return {
        "@odata.context": "/redfish/v1/$metadata#Thermal.Thermal",
        "@odata.id": "/redfish/v1/Chassis/1/Thermal",
        "@odata.type": "#Thermal.v1_7_2.Thermal",
        "Id": "Thermal",
        "Name": "Thermal Subsystem",
        "Temperatures": temps,
        "Fans": fans_data,
    }


@router.get("/Systems")
@router.get("/Systems/")
def list_systems():
    """Redfish Systems Collection."""
    return {
        "@odata.context": "/redfish/v1/$metadata#ComputerSystemCollection.ComputerSystemCollection",
        "@odata.id": "/redfish/v1/Systems",
        "@odata.type": "#ComputerSystemCollection.ComputerSystemCollection",
        "Name": "Computer System Collection",
        "Members@odata.count": 1,
        "Members": [{"@odata.id": "/redfish/v1/Systems/1"}],
    }


@router.get("/Systems/1")
@router.get("/Systems/1/")
def get_system_detail():
    """Redfish Systems/1 Detail: Compute & Memory Telemetry."""
    stats = _get_stats()
    mem = stats.get("mem", {})
    cpu = stats.get("cpu", {})

    return {
        "@odata.context": "/redfish/v1/$metadata#ComputerSystem.ComputerSystem",
        "@odata.id": "/redfish/v1/Systems/1",
        "@odata.type": "#ComputerSystem.v1_20_0.ComputerSystem",
        "Id": "1",
        "Name": "Kiboto Host System",
        "SystemType": "Physical",
        "Manufacturer": _made_by(stats)[0],
        "Model": _made_by(stats)[1],
        "PowerState": "On",
        "Status": {"State": "Enabled", "Health": "OK"},
        "ProcessorSummary": {
            "Count": 1,
            "Model": str(cpu.get("model") or "") or "x86_64 Multi-Core Processor",
            "Status": {"State": "Enabled", "Health": "OK"},
        },
        "MemorySummary": {
            # no 32 GiB is made up while the first reading is not in
            "TotalSystemMemoryGiB": float(mem["total_gb"]) if mem.get("total_gb") is not None else None,
            "Status": {"State": "Enabled", "Health": "OK"},
        },
        "Storage": {"@odata.id": "/redfish/v1/Storage"},
    }


@router.get("/Storage")
@router.get("/Storage/")
def list_storage():
    """Redfish Storage Collection."""
    return {
        "@odata.context": "/redfish/v1/$metadata#StorageCollection.StorageCollection",
        "@odata.id": "/redfish/v1/Storage",
        "@odata.type": "#StorageCollection.StorageCollection",
        "Name": "Storage Subsystem Collection",
        "Members@odata.count": 1,
        "Members": [{"@odata.id": "/redfish/v1/Storage/1"}],
    }


@router.get("/Storage/1")
@router.get("/Storage/1/")
def get_storage_detail():
    """Redfish Storage/1 Detail: Drives & Volumes."""
    stats = _get_stats()
    disks = stats.get("disks", [])

    drives_members = []
    for d in disks:
        dev = d.get("dev") or d.get("name", "disk")
        drives_members.append({"@odata.id": f"/redfish/v1/Storage/1/Drives/{dev}"})

    return {
        "@odata.context": "/redfish/v1/$metadata#Storage.Storage",
        "@odata.id": "/redfish/v1/Storage/1",
        "@odata.type": "#Storage.v1_16_0.Storage",
        "Id": "1",
        "Name": "Kiboto Storage Array",
        "Status": {"State": "Enabled", "Health": _worst([_drive_health(d) for d in disks])},
        "Drives@odata.count": len(drives_members),
        "Drives": drives_members,
    }


@router.get("/Storage/1/Drives/{drive_id}")
def get_drive_detail(drive_id: str):
    """Redfish Storage/1/Drives/{drive_id}: Individual Drive Telemetry."""
    stats = _get_stats()
    disks = stats.get("disks", [])

    target = None
    for d in disks:
        dev = d.get("dev") or d.get("name", "")
        if dev.lower() == drive_id.lower():
            target = d
            break

    if not target:
        raise HTTPException(status_code=404, detail=f"Drive {drive_id} not found.")

    is_standby = target.get("standby", False)
    is_nvme = "nvme" in drive_id.lower()
    dev = str(target.get("dev") or target.get("name") or drive_id)

    return {
        "@odata.context": "/redfish/v1/$metadata#Drive.Drive",
        "@odata.id": f"/redfish/v1/Storage/1/Drives/{drive_id}",
        "@odata.type": "#Drive.v1_17_0.Drive",
        "Id": drive_id,
        "Name": f"Physical Drive {drive_id}",
        "MediaType": _media_type(target, dev),
        "Protocol": "NVMe" if is_nvme else "SATA",
        "CapacityBytes": _capacity(target),
        "Status": {
            "State": "StandbyOffline" if is_standby else "Enabled",
            "Health": _drive_health(target),
        },
    }
