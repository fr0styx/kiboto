# Kiboto OS: a machine of its own

Here Kiboto is the system of the machine instead of an app on another NAS system: it makes the
storage pools, shares the folders, runs the apps and updates itself. Underneath is a plain
Debian 13, which keeps doing what it does (boot, drivers, its own updates with `apt`).

Kiboto OS is in beta. It is tested on its reference box and on a Debian 13 virtual machine with
real disks handed to it, not yet on a range of real hardware. Use it on a machine whose disks hold
nothing you need. Every build is also installed in a fresh Debian 13 virtual machine, and looked at
before and after a restart, before it is signed or published.

What it can do today, beside what Kiboto Companion (the container) can do, is in the
[feature list](FEATURES.md).

1. [What it runs on](#what-it-runs-on)
2. [What we promise while it is in beta](#what-we-promise-while-it-is-in-beta)
3. [Install from the USB image](#install-from-the-usb-image)
4. [Check the download](#check-the-download)
5. [Install on a Debian you set up yourself](#install-on-a-debian-you-set-up-yourself)
6. [The first sign-in](#the-first-sign-in)
7. [What it changes on the machine](#what-it-changes-on-the-machine)
8. [The firewall](#the-firewall)
9. [Updates](#updates)
10. [A new system disk](#a-new-system-disk)
11. [Taking it off again](#taking-it-off-again)

Already running Kiboto Companion? [CHOOSE_AND_MOVE.md](CHOOSE_AND_MOVE.md) says how to move, with your pools
and a settings backup.

## What it runs on

| Part | What Kiboto needs | Good to know |
| --- | --- | --- |
| Processor | A 64-bit PC (amd64: Intel or AMD) | ARM boards are not supported as a machine of their own; the container runs on them. Virtual machines need Intel VT-x or AMD-V turned on in the firmware. |
| Memory | 4 GB or more | 8 GB or more for apps, virtual machines or local AI. ZFS uses free memory as a read cache and gives it back when apps need it. |
| System disk | A disk of its own, 32 GB or more; an SSD is best | Only Debian and Kiboto live there: a fresh install uses about 5 GB. It never holds your files, and setup never offers it as storage. |
| Storage drives | SATA or NVMe drives on the board, or on a controller in HBA (IT) mode | ZFS, btrfs and ext4 want to see each drive as it is: a RAID card that hides the drives behind its own volumes is the wrong kind. USB drives are fine for backups; in a pool they are slow and can drop off, so they are not recommended there. |
| Network | A wired Ethernet port Debian has a driver for | Wi-Fi is not set up by the installer or by Kiboto. VLANs, bonds, packet size, IPv6 and further routes are set under Network. |
| Firmware | UEFI or the older BIOS mode, Secure Boot on or off | With Secure Boot on, ZFS is signed with a key of the machine's own, which the firmware learns once: at the next start after the install, at the machine's screen (see below). |
| Security chip | Optional: a TPM 2.0 | With one, the key for the AI chats and search index is sealed to the machine; without one, to its system disk. |
| Fans, front screen, light bar | Driven on the reference box only | Elsewhere Kiboto shows the temperatures and the fans stay with the firmware. |

**Before you buy or wipe anything**, start the machine from any Debian 13 live USB and run
`sh hardware_report.sh > report.txt` (it is in `scripts/` in this repository). It only reads: nothing
is mounted, written, installed or sent, no drive is asked anything, and serial numbers and network
addresses are left out, so you can share the report. It lists the processor, memory, firmware mode,
TPM, every drive controller and network port with its driver. Reports of what does and does not
work are welcome as an issue.

## What we promise while it is in beta

- **Tested on one model, community elsewhere.** Other 64-bit PCs will most likely work, because the
  drivers are Debian's.
- **Debian fixes the base, Kiboto fixes the app.** The kernel, the drivers and the system packages
  get their fixes from Debian, through `apt`: its security fixes are installed by themselves every
  day, the kernel included. Kiboto fixes Kiboto, its install script and how it drives the machine,
  and holds ZFS and Docker at the versions it was tested with until a release moves them.
- **No response time while in beta.** Issues are read and fixed as time allows. Security reports
  follow [SECURITY.md](../SECURITY.md).
- **The source of everything on the image.** The install image is Debian's own netinst image with
  Kiboto's files added; `kiboto/NOTICE.txt` on it says where Debian publishes the source of its
  software and offers that source on request for three years after each release.

## Install from the USB image

From 2.0.8 on, each release carries the image as `kiboto-<version>-install.iso` (about 800 MB)
beside `install.sh`, while Kiboto OS is in beta on the
[releases page](https://github.com/fr0styx/kiboto/releases) (2.0.7 was not published).

1. Download the image, `SHA256SUMS` and `SHA256SUMS.sigstore.json` from the release page, and
   [check them](#check-the-download).
2. Write the image to a USB stick of 1 GB or more. balenaEtcher (Windows, Mac, Linux) or Rufus in
   "DD image" mode (Windows) do it in a few clicks. On Linux:
   `sudo dd if=kiboto-<version>-install.iso of=/dev/sdX bs=4M conv=fsync status=progress`, where
   `/dev/sdX` is the stick (everything on it is lost).
3. Secure Boot may stay on. Kiboto then signs ZFS with a key of the machine's own, and one step is
   left after the install: at the next start a blue screen asks to "Perform MOK management"; press
   a key, choose Enroll MOK, Continue, Yes, type the code the screen showed after the install (it is
   also on the screen above the sign-in prompt) and choose Reboot. Storage pools are ready after
   that, and About in Kiboto says when the step is still open.
4. Start the machine from the stick (the firmware's boot menu, often F12, F11 or Esc at power-on).
   "Install Kiboto" is chosen after ten seconds.
5. Debian's own installer asks two things only: which disk becomes the system disk (it shows them
   with size and model, then asks before writing) and a root password. No other disk is touched.
6. When the machine starts again, Kiboto installs itself (about ten minutes, most of it building
   ZFS) and the screen shows the code for the first sign-in.
   If it stops, for example without a network, the screen says why. Put it right and restart the
   machine to try again. The whole log is in `/var/log/kiboto-install.log`.

Root may sign in over SSH with that password until the first sign-in to Kiboto's page. That turns
password sign-in over SSH off; keys put on the image still sign in, and Network, This machine has
the switch to turn passwords back on. The firewall starts on: devices at home reach everything,
the outside reaches nothing until you tick it (see [the firewall](#the-firewall)).

To build the image yourself: `sh packaging/image/build-image.sh debian-13-netinst.iso <kiboto
image>@sha256:<digest> kiboto.iso` turns Debian's official 13 netinst image into Kiboto's install
image (needs `xorriso`). `KIBOTO_ROOT_KEYS=<file>` puts SSH keys on the image that may sign in as
root too.

## Check the download

Each release lists the SHA-256 of `install.sh` and of the install image in `SHA256SUMS`, signed by
this project's build service with Sigstore (no key to trust by hand). In the folder you downloaded
them to:

```sh
sha256sum -c SHA256SUMS --ignore-missing
cosign verify-blob SHA256SUMS --bundle SHA256SUMS.sigstore.json \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github\.com/fr0styx/kiboto/\.github/workflows/ci\.yml@refs/tags/v'
```

The first says each file you have is the one the release made; the second that `SHA256SUMS` was
made by this repository's release workflow for a version tag, which waits for the maintainer's
approval.

## Install on a Debian you set up yourself

You need a fresh, minimal Debian 13 on the machine's own system disk: in the Debian installer,
choose "SSH server" and "standard system utilities" only. No Samba, NFS server or containers set
up on it yet: the install script stops if it finds them, because Kiboto writes those settings
itself.

Every release from 2.0.6 on carries an `install.sh` that names that release's image by its digest.
Download it from the release page, [check it](#check-the-download), read it if you like, then run it
as root:

```bash
sh install.sh
```

It installs the tools Kiboto drives (ZFS, btrfs and ext4 tools, Samba, the NFS server, Docker,
QEMU), takes Kiboto's own files out of the release image, checks that Kiboto's own build service
signed that image (against the public Sigstore log), and starts Kiboto as a service. A version that
is not signed is taken out again and nothing changes; `--unsigned` after the image installs a build
of your own without that check. On a small machine this takes about ten minutes, most of it
building the ZFS module.

## The first sign-in

At the end of the install the script prints the address to open and a one-time code. The same code
is on the machine's own screen and in its SSH greeting until you have chosen your password. Open the
address from another computer, enter the code, and choose the administrator's password. Setup then
helps you make a pool from the other drives; the system disk is never offered.

Write down the recovery key under Settings, Security: with it a new system disk can open the
encrypted AI chats and search index again.

## What it changes on the machine

- A Debian installed with Debian's own installer runs its network with ifupdown. At the end of the
  install the script moves the same settings to systemd-networkd, so Kiboto can change the address
  under Network. If the machine cannot reach its router afterwards, it goes back to ifupdown by
  itself after 90 seconds; ifupdown's file is kept as `/etc/network/interfaces.kiboto-before`.
- Under Network, Kiboto changes each port's address (from the router or fixed), its DNS servers
  (IPv4 or IPv6), IPv6 (from the router, off or fixed), further routes through other routers, VLANs,
  the packet size, a bond of ports, Wake-on-LAN and a bridge for virtual machines. Each change is a
  trial: unless you keep it within the time shown, the machine puts the old settings back by itself.
  Kiboto writes only its own systemd-networkd files (`/etc/systemd/network/05-kiboto-*` and
  `10-kiboto-*.link`); a port run by any other file is shown and left alone.
- Kiboto's files are in `/opt/kiboto`, its settings in `/var/lib/kiboto`, and
  `/etc/kiboto/kiboto.env` takes extra settings (one `NAME=value` per line).
- Three services: `kiboto`, `kiboto-pools`, which brings your pools back at start before anything
  that uses them, and `kiboto-door`, the only part that runs as root: it changes the machine for
  Kiboto from a fixed list of operations. Kiboto itself runs as the user `kiboto`
  (`python -m backend.services.web_user off` in `/opt/kiboto/current` runs it as root again).
- Pools are mounted under `/mnt/storage`.
- ZFS is Debian 13's own (2.3), and Kiboto makes ZFS pools limited to its features
  (`compatibility=openzfs-2.3-linux`), so a pool opens on any Debian 13 and on every later ZFS. A
  machine installed by an earlier version keeps the newer ZFS from Debian's backports.
- ZFS and Docker are held at the versions Kiboto was tested with (`apt-mark showhold` lists them).
  Everything else updates with `apt` as on any Debian, and you can install your own packages.
- `/etc/samba/smb.conf` is replaced by a line that points at Kiboto's own settings; the file Debian
  shipped is kept beside it as `smb.conf.debian`.
- The key that encrypts the AI chats and search index is made at the first start and sealed to the
  machine's security chip (or its system disk without one), in `/etc/kiboto/keys`.
- A copy of the settings, encrypted, is kept on every pool (`.kiboto` at the pool's root), and apps
  keep their data on the first pool.

## The firewall

On a machine installed from the USB image it starts on; on one set up with `install.sh` it is off
until you turn it on (Settings, Security, **Firewall**). When it is on:

- **Your home network reaches everything on the machine**, whatever is ticked: this page, shared
  folders, every app. Nothing at home stops working because a port was missing from a list.
- **The outside reaches only what you tick**: this page, SSH, shared folders (Windows and Mac, or
  NFS), WebDAV, SFTP, Tailscale, and **Apps** for the ports apps publish. Nothing is ticked at first.

The home network is the private address ranges (10.x, 172.16 to 172.31, 192.168.x), Tailscale's
addresses, and the IPv6 network the machine is on. Kiboto looks at that IPv6 network again every
quarter of an hour, because an internet provider changes it now and then.

Turning the firewall on while you are connected from outside the home network is refused unless
this page is ticked, so you cannot shut yourself out. Kiboto keeps one table of its own
(`inet kiboto`) and leaves every other rule on the machine alone, Docker's included; the page shows
the exact rules under **Show the rules**.

If the machine's network uses public addresses rather than the home ranges (some offices do), its
page cannot be reached with the firewall on. At the machine itself, `nft delete table inet kiboto`
opens it until the next start; then tick **Kiboto (this page)** or turn the firewall off.

Most homes sit behind a router that already lets nothing in from the internet. The firewall matters
when the machine has an address the internet can reach: a public IPv6 address, a port forwarded on
the router, or a network you share with people you do not know.

## Updates

Kiboto updates itself from the Updates page as it does elsewhere. A new version is put beside the
running one and switched to; if it does not start, the machine goes back to the version before and
says so. "Revert" goes back to the version before the last update, with the settings as they were
then. ZFS and Docker move only when a Kiboto release was tested with newer ones: Updates then offers
them. A version's Python packages come out of its own image, the one whose signature was checked, so
an update downloads nothing from the Python package index; only a version whose image has none for
the machine's Python installs them with `pip`, from the hashes the version names.

Debian's security fixes are installed by themselves every day (Debian's `unattended-upgrades`, set
to Debian's security archive only, in `/etc/apt/apt.conf.d/52kiboto-security`), the kernel included.
Kiboto never restarts the machine for them; Updates says when a restart finishes one. A new kernel
starts only once ZFS is built for it: until then a hook (`/etc/kernel/postinst.d/zzz-kiboto-zfs`)
keeps GRUB on the kernel that runs now, and Updates says which kernel waits. `KIBOTO_SECURITY_UPDATES=0`
turns the automatic fixes off and holds the kernel again. Debian's point releases come when you
update with `apt`, as on any Debian.

The machine stays on Debian 13. Kiboto's Python environment, its root service and its updater are
made for Debian 13's Python, and a move to Debian 14 would stop all three at once, with nothing left
in the browser to repair it. So a file of apt's, `/etc/apt/preferences.d/kiboto-debian13.pref`,
keeps apt from installing packages of any other Debian release; Debian 13's own updates, backports
and other sources are not affected. A Kiboto release made for Debian 14 will move the machine
itself. To let apt move it anyway, set `KIBOTO_KEEP_DEBIAN=0` in `/etc/kiboto/kiboto.env` and
restart Kiboto: the file is then taken away. If the machine was moved and Kiboto no longer starts,
running the install script again puts Kiboto back on the new Python.

## A new system disk

The system disk holds nothing you cannot get back. If it dies, put in a new one, install again from
the USB image, and choose "Look on this machine's drives" in setup: Kiboto finds the settings copy
on your pools, asks for the recovery key, brings the pools back and restarts with your people,
shares and apps as they were.

## Taking it off again

```bash
sh /opt/kiboto/current/packaging/install.sh --uninstall
```

Kiboto's service and files go; your pools, shared folders and apps are not touched, and the packages
stay installed. Add `--purge` to remove Kiboto's settings as well.
