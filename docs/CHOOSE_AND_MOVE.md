# Choose a Kiboto, and move to Kiboto OS

Kiboto comes in two editions. They run the same app; what differs is who runs the drives and the
machine. [FEATURES.md](FEATURES.md) compares them feature by feature.

## Which one

| You have | Choose | Why |
| --- | --- | --- |
| Unraid, TrueNAS SCALE, Proxmox, FygoOS, UGOS or ZettOS, and want to keep it | **Kiboto Companion** beside it | Your NAS system keeps running the drives, the array and its own updates. Kiboto adds the desktop, people, apps, backups and Kib on top, and shows what the NAS system manages. |
| A Debian or Ubuntu machine with Docker, and no NAS system | **Kiboto Companion** on plain Linux | Kiboto makes new pools and shares; the machine stays yours to run. |
| A machine you can give to Kiboto entirely, with a disk of its own for the system | **Kiboto OS** (beta) | Kiboto runs the drives, the firewall, updates of the system and the shares itself. amd64 only for now. |

You can start with Companion and move later. Kiboto OS is in beta: read
[KIBOTO_OS.md](KIBOTO_OS.md#what-we-promise-while-it-is-in-beta) first.

## Before you move

- **The pools must be ones Kiboto OS can take: ZFS pools, and btrfs, ext4 or XFS file systems with
  a label.** Unraid's array keeps each drive as a file system of its own, protected by a parity
  drive. Kiboto OS can take each of those drives as a pool of its own, but it does not keep Unraid's
  parity, so they would lose their protection: move their files onto a pool that keeps two copies
  (a ZFS mirror or btrfs RAID1) first, or stay on Companion.
- **Kiboto OS needs a system disk of its own.** It is never a drive of a pool: the install wipes it.
- **Have a copy of your files outside this machine**, as before any change of system.

## Move from Companion to Kiboto OS

1. **In Companion, download a settings backup.** Settings → *Kiboto's settings file* → **Download
   Backup**, with a passphrase of at least 8 characters. It holds the people and their passwords,
   the shares, the apps' settings, the cloud accounts and the off-site backups' keys. Keep the file
   and the passphrase somewhere other than this machine.
2. **Install Kiboto OS** on its system disk from the install image ([KIBOTO_OS.md](KIBOTO_OS.md#install-from-the-usb-image)),
   with the pool drives connected, and sign in for the first time.
3. **Import each pool:** Storage → **Import Pool**. Do this before the next step and before adding
   anyone on Kiboto OS: a person made there first may take the account number a person in the
   backup has, and then that person gets no share account.
4. **Restore the settings backup:** Settings → *Kiboto's settings file* → **Restore Backup**, the file
   and its passphrase, then **Restart now**. Kiboto restarts and asks you to sign in with the
   password from the backup.
5. **Shares follow their pool.** Companion often saw one pool as its whole storage folder (on
   TrueNAS, `/mnt/tank` as `/mnt/storage`). On Kiboto OS each pool is a folder of its own
   (`/mnt/storage/tank`), so Kiboto points each share whose folder is not there at the one pool that
   holds a folder by that path. Nothing is moved or made. A share whose folder is on no pool yet is
   tried again when a pool is imported; one found on two pools stays as it was, for you to fix in
   Storage.
6. **Each person signs in once.** The backup keeps passwords only in a form the file server cannot
   use, so a person's Windows and Mac shares open again after their first sign-in to Kiboto OS. A
   person with two-step sign-in makes a share password in their profile, as before.
7. **Check the apps.** Their folders on the pools stay. Install again from the App Catalog any app
   that does not run.

## What does not come along

- The settings of the NAS system Companion ran beside (Unraid's or TrueNAS's own shares, users and
  schedules). Kiboto OS makes its own from Kiboto's settings.
- Containers that Kiboto did not install.
- Anything only on Companion's machine outside the pools and the settings backup.

## Going back

The move changes nothing on the pools but the files you change afterwards, so Companion can take
them again: import them on the NAS system (a ZFS pool may have to be forced, as Kiboto OS was the
last to use it), start the container with its data folder if you kept it, and its settings are as
you left them.
