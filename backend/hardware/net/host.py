"""Who changes the host's network wiring (SET-16, decision D2).

Kiboto reads the host's network on every install. It changes the wiring (address, packet size,
link speed, Wake-on-LAN, bonds, bridges, VLANs) only on a host it manages: Kiboto's own OS images
and a Debian machine set up for it (managed.py). Everywhere else the host's own settings own the wiring, and a change made
from Kiboto never applied or did not survive a restart (network report, B2 to B4).

The page asks `capabilities()` and draws each setting as a row that becomes a field once the host
allows it. The write routes keep their shape and answer "not on this host" with where to change it.
A managed host subclasses `HostNetwork`, sets `managed = True`, implements `apply()` and is
returned by `current_host()` for its platform.
"""

from typing import Any

from backend import door
from backend.hardware.pal.base import PlatformType

SETTINGS = ("address", "mtu", "speed", "wake_on_lan", "bond", "bridge", "vlan")

# where the host's own network settings are, for the sentence the page shows
_WHERE = {
    PlatformType.UNRAID: "unraid",
    PlatformType.TRUENAS: "truenas",
    PlatformType.PROXMOX: "proxmox",
    PlatformType.UGOS: "ugos",
}
_WHERE_TEXT = {
    "unraid": "Unraid: Settings, Network Settings",
    "truenas": "TrueNAS: Network",
    "proxmox": "Proxmox: the node's System, Network",
    "ugos": "UGOS: Control Panel, Network",
    "system": "the host system's own network settings",
    "debian": "Debian's own network settings on this machine",
}


class NotOnThisHost(Exception):
    """A change to the wiring on a host whose own settings own it."""

    def __init__(self, setting: str, where: str):
        self.setting = setting
        self.where = where
        super().__init__(f"This is changed in {_WHERE_TEXT.get(where, _WHERE_TEXT['system'])}, not in Kiboto.")


class HostNetwork:
    """A host Kiboto does not manage: it reads the wiring and changes none of it."""

    managed = False

    def __init__(self, platform: PlatformType | str = PlatformType.UNKNOWN):
        self.platform = platform

    def where(self) -> str:
        return _WHERE.get(self.platform, "system")  # type: ignore[call-overload]

    def capabilities(self) -> dict[str, Any]:
        return {
            "managed": self.managed,
            "where": self.where(),
            "can_change": {name: self.managed for name in SETTINGS},
        }

    def apply(self, setting: str, target: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Changes one setting of one interface (or the address). A managed host overrides this."""
        raise NotOnThisHost(setting, self.where())


# what a machine set up for Kiboto changes itself, each as a trial (managed.py); speed and Wake-on-LAN
# follow later
MANAGED_SETTINGS = ("address", "vlan", "mtu", "bond")


def _address_now() -> dict[str, Any]:
    """The address the machine shows, for a port whose settings are not in Kiboto's own file yet."""
    from backend.hardware.net import host_ip

    try:
        return host_ip.get_host_ip_config()
    except (OSError, ValueError, KeyError):  # unreadable: a port with Kiboto's own file does not need it
        return {}


class ManagedHostNetwork(HostNetwork):
    """A machine set up for Kiboto (managed.py): its address, VLANs, packet sizes and bond are Kiboto's."""

    managed = True

    def where(self) -> str:
        return "debian"

    def capabilities(self) -> dict[str, Any]:
        from backend.hardware.net import managed

        can = managed.networkd_runs()
        return {
            "managed": True,
            "where": self.where(),
            "can_change": {name: (can and name in MANAGED_SETTINGS) for name in SETTINGS},
            # a change being tried, so a page opened in the middle shows it (root keeps its record)
            "trial": door.via("network.trial_status", managed.trial_status),
        }

    def apply(self, setting: str, target: str, changes: dict[str, Any]) -> dict[str, Any]:
        from backend.hardware.net import managed

        if setting not in ("address", "vlan", "port", "bond") or not managed.networkd_runs():
            raise NotOnThisHost(setting, self.where())
        from backend import door

        if setting == "vlan":
            if changes.get("delete"):
                return door.via("network.remove_vlan", managed.start_vlan_removal, name=target)
            vlan_id = changes.get("vlan_id")
            if not isinstance(vlan_id, int) or isinstance(vlan_id, bool):
                raise ValueError("A VLAN number is between 1 and 4094.")
            return door.via(
                "network.try_vlan", managed.start_vlan_trial, parent=target, vlan_id=vlan_id, now=_address_now()
            )
        if setting == "bond":
            if target != managed.BOND:
                raise ValueError(f"Kiboto makes one bond here, {managed.BOND}.")
            if changes.get("delete"):
                return door.via("network.remove_bond", managed.start_bond_removal)
            miimon = changes.get("miimon")
            return door.via(
                "network.try_bond",
                managed.start_bond_trial,
                members=list(changes.get("slaves") or []),
                mode=str(changes.get("mode") or "1"),
                miimon=miimon if isinstance(miimon, int) and not isinstance(miimon, bool) else 100,
                now=_address_now(),
            )
        if setting == "port":
            other = sorted(set(changes) - {"mtu"})
            if other:  # speed and Wake-on-LAN are not Kiboto's here yet
                raise NotOnThisHost(other[0], self.where())
            if changes.get("mtu") is None:
                return {"status": "ok"}
            return door.via(
                "network.try_mtu", managed.start_mtu_trial, port=target, mtu=int(changes["mtu"]), now=_address_now()
            )

        # through the host door where it runs (ADR 0006)
        if "confirm" in changes:
            return door.via("network.keep", managed.keep, key=changes["confirm"])
        if "revert" in changes:
            return door.via("network.go_back", managed.go_back, key=changes["revert"])
        return door.via("network.try_address", managed.start_trial, changes=changes)


def current_host() -> HostNetwork:
    """The host Kiboto runs on: a machine set up for Kiboto is managed, every other host is read."""
    from backend import runtime
    from backend.hardware.pal.detect import StoragePlatformDetector

    platform = StoragePlatformDetector.detect()
    if runtime.managed_host():
        return ManagedHostNetwork(platform)
    return HostNetwork(platform)
