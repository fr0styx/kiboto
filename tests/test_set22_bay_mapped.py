"""SET-22 Storage decision 4 a: the bay data says which drives come from the saved mapping and which
were put in a bay by guess."""

from unittest.mock import patch

from backend.hardware.chassis import ChassisEngine, PhysicalDiskRecord


def _disk(dev, cid):
    return PhysicalDiskRecord(
        dev_name=dev,
        canonical_id=cid,
        dev_path=f"/dev/{dev}",
        transport="sata",
        controller_driver="ahci",
        is_rotational=True,
        role="data",
    )


def test_a_mapped_bay_and_a_guessed_bay_are_told_apart():
    disks = [_disk("sda", "ata-A"), _disk("sdb", "ata-B")]
    cfg = {"profile": "compact_dual", "total_bays": 3, "mappings": [{"slot_index": 2, "canonical_id": "ata-B"}]}
    with (
        patch("backend.hardware.chassis.DiskDiscoveryHAL.discover_physical_disks", return_value=disks),
        patch("backend.hardware.chassis.ChassisEngine.load_bay_mapping_config", return_value=cfg),
        patch("backend.hardware.chassis.ChassisEngine._read_dmi_product_name", return_value="Zettlab D4"),
    ):
        bays = ChassisEngine.get_chassis_status()["bays"]
    by_slot = {b["slot_index"]: b for b in bays}
    assert by_slot[2]["disk"]["canonical_id"] == "ata-B" and by_slot[2]["mapped"] is True
    assert by_slot[1]["disk"]["canonical_id"] == "ata-A" and by_slot[1]["mapped"] is False  # put there by guess
    assert by_slot[3]["is_populated"] is False
