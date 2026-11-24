# ADR 0006: The web process without root, behind a host door

- **Status:** Accepted (23 Nov 2026: the owner chose group and ACL access for people's files)
- **Progress:** steps 1 (the door), 2 (the machine's settings, the network, the firewall), 3 (accounts, Samba, NFS), 4 (snapshots, scrubs, pools, shared folders, SMART self-tests, drive sleep), 5 (updates, going back, packages; the door checks an image's signature itself), 6 (the data key, fans; the front screen gets its device by group at step 9), 7 (the Docker proxy runs in the door), 8 (the door hands what Kiboto makes to the folder's people) built; step 9 can be turned on by root (`python -m backend.services.web_user on`, off by default) and runs on the test machine: files, uploads, the Recycle Bin, shared folders, snapshots, the data key, drive health, machine settings, the firewall, people, backups, apps and virtual machines work (bridged too, on a tap device the door makes), with kernel modules, kernel settings, cgroups and set-id files closed to it; tests/test_adr6_spawns.py fails the build when a file starts more programs than its baseline
- **Date:** 2026-11-23
- **Decides:** how a machine Kiboto runs keeps a bug in the web app from becoming root on the machine

## Context

On a machine Kiboto runs, `kiboto.service` runs the whole backend as root: the web app, the API,
the file services and everything that changes the machine. A remote code execution bug in any
route is root on the machine. The build order lists this among the eight things that must be
true before strangers trust Kiboto with their only copy: "the host door accepts only a fixed list
of operations, and the web process no longer runs as root."

What the backend does today that needs root (counted on 23 Nov 2026 from the code):

| Area | What it runs or touches |
|---|---|
| Storage | `zpool`, `zfs`, `btrfs`, `mkfs.btrfs`, `mkfs.ext4`, `mount`, `umount`, `wipefs`, `mdadm`, `chattr`, `udevadm`, `blkid`, `findmnt`; quotas; raw devices for SMART (`smartctl`) and drive sleep (`hdparm`) |
| Accounts and file servers | `useradd`, `userdel`, `smbpasswd`, `smbcontrol`, `exportfs`; `/etc/samba`, the exports file |
| The machine | `hostnamectl`, `timedatectl`, `systemctl`, `systemd-run`, `networkctl`, `ip`, `nft`, `ethtool`; `/etc/systemd/network`, `/etc/hosts`, `/etc/issue.d`, `/etc/motd.d` |
| Packages and updates | `apt-get`, `dpkg`, `apt-mark`; `/opt/kiboto` (the update and the way back) |
| Hardware | `/sys/class` (fans, the RTC wake-up, LEDs), `/dev/fb0` (the front screen), USB serial and HID devices (light bar, UPS), `/dev/kvm`, `ledctl` |
| Docker | the Docker socket (root-equivalent), already behind the allow-list proxy |
| Keys | `systemd-creds` and the TPM, `/etc/kiboto/keys` |
| People's files | the Files app, uploads, WebDAV, SFTP, copies, the Recycle Bin, snapshots, the AI index, the malware scan, the ransomware guard: reading and writing files owned by many people, and handing new files to the folder's owner (`chown`) |

That is 39 system programs across about 60 modules, and about 230 system paths. Most of them sit
behind a handful of entry points (the storage adapter, `samba_host`, `host_basics`,
`net/managed`, `native_update`, `owned`), which is what makes a split possible.

## Decision (proposed)

### Two processes

- **`kiboto-door`**, a new systemd service running as root, listens on `/run/kiboto/door.sock`
  (mode 0660, group `kiboto`) and accepts connections only from the `kiboto` user (checked with
  `SO_PEERCRED`). It runs a **fixed list of operations**, each a function with typed, checked
  arguments: no shell, no free-form command, no path outside the storage folders and Kiboto's own
  data folder. The Docker allow-list proxy moves into it, since the Docker socket is root.
- **`kiboto`**, the web app and everything else, runs as the unprivileged user `kiboto`, with
  `NoNewPrivileges`, `ProtectSystem=strict` and no capabilities. It asks the door for anything
  that changes the machine.

The operations are the entry points above, not the programs: `storage.create_pool`,
`storage.import`, `storage.snapshot`, `accounts.ensure`, `samba.reload`, `network.try`,
`host.set_name`, `firewall.apply`, `update.switch`, `hardware.set_fan` and so on, about 60 in
all. Each one validates what it is given as the API does today (pool names, single names, paths
resolved inside the storage roots) and writes an audit line.

### People's files without root

The web process needs to read and write every shared folder and every person's private folder.
Two ways were weighed:

1. **Group and ACL access (chosen).** Shared folders already belong to the file server's
   group `users`; the `kiboto` user joins that group. The folder that holds the private homes gets
   a default ACL giving `kiboto` access, so the web process can enter each home while other people
   still cannot. Handing a new file to the folder's owner (today `owned.py`, a `chown`) becomes a
   door operation confined to the storage roots. Fast (no extra hop for reads and writes) and
   simple.
2. **File descriptors from the door.** The door opens each file and passes the descriptor over
   the socket (`SCM_RIGHTS`). Tighter, because the web process could not open anything by itself,
   but every file operation crosses the socket and the file code changes throughout.

Either way, a bug in the web app can still reach the data in the shared folders (it is the
program that serves them) and the operations the door offers. What it can no longer do is change
the machine outside them: install packages, read other disks, rewrite `/etc`, load modules.

### Order of work

Each step ships on its own and keeps the machine working, with the web process still root until
the last step:

1. The door's skeleton: the service, the socket, the peer check, the operation list, the audit,
   and a client the backend uses when the door is there (and calls the code directly when not:
   containers and tests).
2. The machine's settings through the door (`host_basics`, `net/managed`, the firewall).
3. Accounts and file servers (`samba_host`, the exports).
4. Storage (the storage adapter's changing calls, quotas, SMART and drive sleep).
5. Updates and packages (`native_update`, the held set).
6. Hardware (fans, the RTC, LEDs, the front screen) and keys.
7. The Docker proxy inside the door.
8. People's files: the group and ACL, the door's `chown`.
9. The switch: `kiboto.service` runs as `kiboto` with no capabilities; a test fails the build if
   the backend runs a system program outside the door.

## What stays as it is

- In a container (Unraid and the other hosts) Kiboto keeps running as it does: the host there is
  someone else's, and the container is the boundary. The door is for machines Kiboto runs.
- Admins stay root-equivalent: an admin may create pools, accounts and VMs, which the door must
  allow. The door narrows what a bug can do, not what an admin may do.

## Risks

- The door's operation list becomes the security boundary, so each operation needs the same
  validation tests the API has (path traversal, option-like names), and a ratchet test that no
  system program is run outside it.
- The Docker proxy still trusts the web process's word that a person confirmed an elevated
  container (`X-Kiboto-Elevated`, sent after the security review of an app or a recreate): an
  admin may install such apps, so the door cannot refuse them, only write each one to
  `docker-proxy-audit.log`. A bug in the web app could ask for one. Closing that needs a
  confirmation the web process cannot make by itself, which is not designed yet.
- Some features read root-only files (`/dev/mem`, kernel logs, other processes in `/proc`); each
  needs a door operation or loses that detail on a machine Kiboto runs.
- Nine steps of about a week each, at our pace: the largest item left before strangers.

## Alternatives not chosen

- **Capabilities on the web process** (`CAP_DAC_OVERRIDE`, `CAP_CHOWN`, `CAP_SYS_ADMIN`): read and
  write any file and mount anything, which is root in all but name.
- **Keep root and add systemd hardening only** (`ProtectSystem`, `ProtectKernelModules`): worth
  doing early as a partial step, but a root process with a writable `/etc` and the Docker socket
  is still root.
