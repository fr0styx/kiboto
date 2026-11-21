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


class ManagedHostNetwork(HostNetwork):
    """A machine set up for Kiboto (managed.py): the address is Kiboto's to change. The rest follows later."""

    managed = True

    def where(self) -> str:
        return "debian"

    def capabilities(self) -> dict[str, Any]:
        from backend.hardware.net import managed

        can = managed.networkd_runs()
        return {
            "managed": True,
            "where": self.where(),
            "can_change": {name: (can and name == "address") for name in SETTINGS},
            "trial": managed.trial_status(),  # a change being tried, so a page opened in the middle shows it
        }

    def apply(self, setting: str, target: str, changes: dict[str, Any]) -> dict[str, Any]:
        from backend.hardware.net import managed

        if setting != "address" or not managed.networkd_runs():
            raise NotOnThisHost(setting, self.where())
        if "confirm" in changes:
            return managed.keep(changes["confirm"])
        if "revert" in changes:
            return managed.go_back(changes["revert"])
        return managed.start_trial(changes)


def current_host() -> HostNetwork:
    """The host Kiboto runs on: a machine set up for Kiboto is managed, every other host is read."""
    from backend import runtime
    from backend.hardware.pal.detect import StoragePlatformDetector

    platform = StoragePlatformDetector.detect()
    if runtime.managed_host():
        return ManagedHostNetwork(platform)
    return HostNetwork(platform)
