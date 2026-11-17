# Storage

**Settings → Storage** starts with one sentence about your drives: all fine, how many things
need a look, or which drives Drive Health keeps an eye on (a drive that works but shows
early signs), with when it was checked and **Check again**.

## Sleeping drives stay asleep

Kiboto never wakes a sleeping drive to look at it. A sleeping drive shows its last reading
and says so ("it was not woken"); one that has never been read yet says that too.

## The bays

The picture of the NAS shows each bay with its drive and Drive Health's verdict. Where
Kiboto had to guess which drive sits in which bay, the bay says **Position not confirmed**;
set it in **Which drive is in which bay**. **Find this drive** lights the drive's bay.

## Replacing a drive

A failing drive, and an empty bay, offer a step-by-step guide:

1. Check that your important files have a copy (Backup, "Are your files safe?").
2. The drive: its model, bay and the end of its serial number.
3. Get a new drive at least as large; a NAS drive (CMR, not SMR) of the same kind is the
   safe choice.
4. Shut the server down, swap the drive, start the server again.
5. Let the pool rebuild, with the steps for your system: Unraid (assign the slot, then a
   rebuild from parity, files readable meanwhile), TrueNAS (Replace, then a resilver), or a
   btrfs, mdadm or ZFS pool's own tool. Kiboto does not rebuild pools by itself yet. Keep
   the server on until the rebuild has finished, and don't erase the old drive until the new
   one holds the data.

On Unraid, a data drive's replacement can't be larger than the parity drive, and a new
parity drive must be at least as large as the largest data drive.

## Drive Health

**Drive Health** reads each drive's own health data on a schedule, explains each finding in
plain words with what to do (reseat a cable, watch it, copy what matters and replace it),
and keeps a report you can save. It only reads drives that are awake.

## Advanced

Under **Advanced**: creating a pool and the bay setup, for people who manage the pools
themselves.
