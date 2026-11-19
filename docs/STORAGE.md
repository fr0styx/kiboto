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

## Checking a new drive

Before you trust a new drive with data, Kiboto can read it from start to end once. Open **Drive
Health**, choose the drive, and press **Check this drive**. The section is there for a drive
that is not in use: not in a pool, with nothing mounted from it, and not the system's own
drive. Kiboto never starts this check by itself.

The check only reads; nothing is written to the drive. It takes hours (a large hard drive can
take most of a day), and the drive stays awake and busy until it ends. You can close the window
and come back: the section shows how far it is, how fast it reads and about how long is left,
and **Stop the check** ends it at any time. Two drives can be checked at once.

It is not the drive's own long self-test. That test runs inside the drive; this one reads every
part of the drive through the cable and the controller, so it also finds a bad cable or bay, and
it shows where the drive is slow. When it ends, Kiboto compares what the drive reports about
itself (moved sectors, sectors waiting to be moved, sectors it could not read, damaged
transfers) with what it reported before, and says one of:

- **Good to use**: every part was read and nothing got worse.
- **Do not trust it with data**: parts could not be read, or the drive reported damage while it
  was read. Send it back if you can.
- **The cable or the bay**: the drive read to the end, but data was damaged on the way. Reseat
  the drive and check it again.

If the drive gets within 3 °C of the temperature Kiboto treats as critical, the check stops
itself and says so; let the drive cool and see to its airflow before starting again. The last
5 results of each drive are kept, and the end of every check is written to the activity log.

## Watching it from your own dashboard

How full the NAS is can be read outside Kiboto, without waking a drive. The metrics page
(`/api/metrics`, Prometheus format) has `kiboto_pool_usage_percent`, `kiboto_pool_free_bytes`,
`kiboto_pool_used_bytes`, `kiboto_pool_total_bytes` and `kiboto_pool_healthy` for each pool, and
`kiboto_storage_usage_percent` and `kiboto_storage_free_bytes` for all of them together. With Home
Assistant connected, the same numbers arrive there as sensors (see
[HOME_ASSISTANT.md](HOME_ASSISTANT.md)), so an automation can warn you when a pool passes 90 %.

Each drive's health is there too: `kiboto_disk_health` is 0 for a good drive, 1 for one showing
wear and 2 for one that is failing, with `kiboto_disk_temp_celsius` and `kiboto_disk_standby`
beside it; Home Assistant gets a "needs a look" sensor per drive.

## When a check finds damaged files

A check (scrub) reads everything on a pool and compares it with its checksums. When it finds
data it cannot repair, a ZFS pool knows which files are hit. Kiboto then sends an alert and
shows a line on the Overview with the pool, how many files and the first names, for example
"Damaged files in tank (3): IMG_0001.jpg, IMG_0002.jpg, report.pdf".

Restore those files from a backup or a snapshot, then run the check again: the list empties
when nothing damaged is left. Up to 100 files are listed. Damage that has no file name (the
pool's own bookkeeping) is counted but not listed. Btrfs pools report how many errors a check
found but not which files, so for them Kiboto shows the count only.
