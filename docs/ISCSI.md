# Disks for other computers (iSCSI)

Kiboto can lend another computer a disk over your network. The other computer sees a drive of
its own and formats it as it likes; on the NAS it is one file in a folder you choose. People use
this for a virtualisation host's virtual machines, a PC's games library, or a backup program
that wants a disk rather than a shared folder.

For sharing files between people, use a shared folder instead: a disk like this belongs to one
computer at a time, and Kiboto cannot look inside it.

It is **off until you turn it on**: **Settings → Network**, among the services there, **Disks
for other computers (iSCSI)**. It is for whoever manages the storage.

## Adding a disk

Turn the service on, press **Add a disk** and fill in:

- **Name**: small letters, digits and hyphens. It becomes part of the disk's full name, which the
  card shows and the other computer asks for (it looks like `iqn.2026-11.net.kiboto:nas:vm-disk`).
- **Size** in GB, from 1 to 65536. The file takes no space on the NAS until the other computer
  writes to it, so a 500 GB disk that holds 20 GB uses 20 GB. Watch the pool's free space: a disk
  can promise more than the pool has.
- **Folder for its file**: one of your shared folders. The file is named after the disk and
  ends in `.iscsi.img`. Kiboto never replaces a file that is already there.
- **User name and password**: every disk has them; there is no disk that anyone on the network
  can open. The password is 12 to 16 characters without spaces, which is what every system that
  connects accepts. It is kept encrypted and is never shown again.
- **Only from this address** (optional): one address such as `192.168.1.20`, or a range such as
  `192.168.1.0/24`. A computer at another address is refused even with the password, and is not
  shown the disk at all.

Up to 8 disks. Saving restarts the service, so a computer that is using a disk is cut off for a
moment; do it when nothing is being written.

## Connecting the other computer

Point it at the NAS's address, port 3260, and sign in with the disk's user name and password
(the method is called CHAP):

- **Windows**: "iSCSI Initiator" → Discovery → Discover Portal → the NAS's address; then Targets
  → Connect → Advanced → Enable CHAP log on.
- **Linux**: `iscsiadm -m discovery -t sendtargets -p <nas>` and then log in with the session's
  CHAP settings.
- **Proxmox, ESXi, Hyper-V**: add iSCSI storage with the NAS's address and the disk's name.

## Changing and removing

A disk can be made larger, never smaller: the other computer's data is on it. Its name and
folder stay as they were made. Leave the password empty when you change something else, and it
stays as it is.

**Remove** takes the disk off the list; the computer that used it can no longer reach it. Its
file stays in its folder, so nothing is lost by a wrong click. Delete the file in Files when you
are sure.

## What to know

- A disk in use keeps the drives its folder is on awake.
- The service is a small program in a container of its own beside Kiboto (`kiboto-iscsi`). It
  needs nothing loaded into the system's kernel and has no special rights; it sees only the
  folders your disks are in.
- Kiboto's firewall, when it is on, lets every device on your home network connect. A computer outside your home network cannot reach port 3260 through it.
- If the card says the service is not running, another program on the NAS is probably using
  port 3260 already.
- Back the file up like any other: it is in a folder, so your backup jobs cover it. A copy
  taken while the other computer is writing may not be consistent; a snapshot of the folder is.
