# What Kiboto can do, by edition

<!-- Written by scripts/feature_matrix.py from docs/feature-matrix.json. Change the source, then run
     `python scripts/feature_matrix.py write`. -->

Kiboto runs in three ways. This page says what each can do today.

- **Kiboto Companion beside another NAS system.** The container on Unraid, TrueNAS SCALE, Proxmox, FygoOS, UGOS or ZettOS. That system keeps running the drives and the machine.
- **Kiboto Companion on plain Linux.** The container on Debian, Ubuntu or any Docker host with no NAS system of its own.
- **Kiboto OS.** A machine of its own: Debian 13 set up by the Kiboto OS install image. Kiboto runs the drives and the machine. In beta.

What the words mean:

- **Yes**: Kiboto does it.
- **Partly**: Kiboto does part of it; the note says which part.
- **View only**: Kiboto shows it; the NAS system changes it.
- **Your NAS system does this**: The NAS system or the Linux beside Kiboto does it, in its own settings.
- **Not yet**: Not there yet on this edition; it is being built.
- **Being checked**: Built, and still being checked on this edition.
- **No**: Not offered here.

## Storage

| | Companion, beside a NAS system | Companion, on plain Linux | Kiboto OS |
| --- | --- | --- | --- |
| Storage pools: create, grow, see their health<br><sub>On plain Linux Kiboto makes new pools but does not take over pools that already exist.</sub> | View only | Partly | Yes |
| Replace a failed drive from the app<br><sub>ZFS and btrfs pools that keep a second copy rebuild onto an empty drive from the app. Tried on a virtual machine, not yet with a real drive.</sub> | Your NAS system does this | Yes | Being checked |
| Windows and Mac shares (SMB) | View only | Yes | Yes |
| NFS shares | Your NAS system does this | No | Yes |
| A private folder for each person | Yes | Yes | Yes |
| USB drives: open and eject | Your NAS system does this | No | Yes |
| Drive sleep | Your NAS system does this | No | Yes |
| Drive Health: checks, warnings, history | Yes | Yes | Yes |
| Settings copy on the pools, to rebuild after a new system disk | No | No | Yes |
| iSCSI targets | Yes | Yes | Yes |
| Merged folders across fast and large drives | Your NAS system does this | Yes | Not yet |
| Copies of a pool to another machine (replication)<br><sub>Kiboto OS copies to another pool of the same machine; copies to another machine over SSH come later.</sub> | Your NAS system does this | Yes | Partly |

## Files, apps and Kib

| | Companion, beside a NAS system | Companion, on plain Linux | Kiboto OS |
| --- | --- | --- | --- |
| File Explorer, previews and share links | Yes | Yes | Yes |
| Apps from the catalog (Docker) | Yes | Yes | Yes |
| Virtual machines<br><sub>Not in the smaller -core image.</sub> | Yes | Yes | Yes |
| Backups and restore | Yes | Yes | Yes |
| SFTP | Yes | Yes | Yes |
| Kib: answers from your own files, on your own hardware | Yes | Yes | Yes |
| People, roles and sign-in with a second step | Yes | Yes | Yes |

## The machine

| | Companion, beside a NAS system | Companion, on plain Linux | Kiboto OS |
| --- | --- | --- | --- |
| Kiboto updates with a way back<br><sub>Kiboto OS follows the Stable and Beta channels; the container can also follow Edge.</sub> | Yes | Yes | Yes |
| System updates: kernel, ZFS, Docker<br><sub>Kiboto OS installs Debian's security fixes by itself, the kernel included, and never restarts the machine for them. ZFS and Docker move to versions a release was tested with.</sub> | Your NAS system does this | Your NAS system does this | Yes |
| Network settings<br><sub>Kiboto OS changes the address and the bridge for virtual machines, with a way back.</sub> | View only | View only | Partly |
| Firewall<br><sub>On after an install from Kiboto's USB image; on other installs off until you turn it on. Your home network reaches everything, and the outside only what you tick, apps included.</sub> | Your NAS system does this | Your NAS system does this | Yes |
| Restart and shut down | Yes | Yes | Yes |
| Power schedule: wake and sleep at set times<br><sub>On Kiboto OS it is tried on a virtual machine, not yet for a night on a real one.</sub> | Yes | Yes | Being checked |
| Battery backup (UPS) | Yes | Yes | Not yet |
| Server name, time zone and the SSH switch | Your NAS system does this | Your NAS system does this | Yes |
| Dynamic DNS, HTTPS certificates, access from away | Yes | Yes | Being checked |

## Front panel hardware (Zettlab D4, D6 and D8 Ultra)

| | Companion, beside a NAS system | Companion, on plain Linux | Kiboto OS |
| --- | --- | --- | --- |
| Fans: curves, quiet at night, fan stop while drives sleep<br><sub>On the D4 the kernel keeps the fans, and Kiboto shows them.</sub> | Yes | Yes | Yes |
| Light bar<br><sub>The Zettlab D4's too, without the rainbow effect.</sub> | Yes | Yes | Being checked |
| Front screen<br><sub>Kiboto OS draws the screen with the plain renderer. The D4's screen is not drawn yet.</sub> | Yes | Yes | Partly |
| Card copies from the SD and microSD slots | Yes | Yes | Yes |
| Fan watchdog beside the app | Yes | Yes | Not yet |

## Where it runs

| | Companion, beside a NAS system | Companion, on plain Linux | Kiboto OS |
| --- | --- | --- | --- |
| Processors | amd64 and arm64 | amd64 and arm64 | amd64 |
| Installed as | A container | A container | An install image for a USB stick, or a script on Debian 13 |

Something here does not match what you see? Please open an issue: the page is kept in step with every
change, and a wrong line is a bug.
