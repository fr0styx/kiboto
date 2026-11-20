# Old files move to the slower drives (data tiering)

A NAS with a fast pool (SSDs) and slower drives (hard drives) can keep the files you use on the
fast pool and let the ones nobody touches move to the slower drives, where space costs less. Kiboto
does this per shared folder, at night, and the folder keeps showing every file in one place.

It is **off for every shared folder** until you turn it on: **Storage → Shared folders → Old files
move to the slower drives**. Only someone who manages the storage can.

## What "old" means

A file is old when, for the number of days you chose for its folder (90 unless you change it, from
7 to 3650):

- nobody opened it, and
- nobody changed it.

Most systems do not record when a file is opened, and making them record it costs a write on every
open. Kiboto listens instead: the system tells it about each open on the fast pool, and Kiboto keeps
the day of the last one in a small record of its own. Nothing about your drives is changed.

Two things follow from that:

- **Kiboto watches first.** When you turn tiering on for a folder, nothing moves until Kiboto has
  watched it for the folder's full number of days. Before that it cannot know that a file was not
  opened. The page shows the date from which files can move.
- **A program that reads through a folder counts as someone opening the files.** A media server
  that scans its library, an antivirus scan or a backup program outside Kiboto opens every file it
  reads, so those files stay on the fast pool. Kiboto's own reading (its search, its backups) does
  not count.

If Kiboto could not listen for more than an hour while the system was running (its container was
stopped, for example), it no longer knows what was opened in that time. It then watches the folders
for their full number of days again, and says so in the activity log. Time the NAS spent switched
off does not count: nobody opened a file then.

## What happens at night

At 03:00 Kiboto looks at each folder that has tiering on and has been watched long enough, and
moves its old files, at most 20000 files a night per folder. The rest follow on later nights.

The move is made by a small program in a container of its own (`kiboto-mover`) that sees only the
folder's two sides, has no network, and exists only while it runs. For each file it:

1. leaves the file alone if someone has it open;
2. copies it to the slower drives under a temporary name and writes it through to the drive;
3. checks the copy, and that the original did not change meanwhile;
4. gives the copy its real name, and only then removes the original.

A file that is already on the slower drives under the same name is never replaced. A file with a
second name (a hard link), a link and a hidden file (its name starts with a dot) are left where
they are. Whatever stops a file from moving leaves it on the fast pool, and it is tried again
another night. The file keeps its owner, its permissions and its dates.

**Moving wakes the slower drives.** If they sleep, they spin up at 03:00 on the nights when there
is something to move, and go back to sleep on their own.

**One way only.** A file that has moved stays on the slower drives, also when you open it again or
turn tiering off. To have it on the fast pool again, copy it there yourself.

"Move now" on the page does the same run at once, for one folder.

On Unraid the files go to **one drive of the array**, written to that drive directly (parity is
kept as for any write to the array). Kiboto uses the drive the folder's files went to last while it
has room, so a folder's old files stay together and fewer drives wake up; otherwise the drive with
the most free space. It only uses drives the share may use (its included and excluded drives, and
the system's), and it leaves the share's minimum free space on the drive. When no drive has room,
nothing is started and the page says so.

## Which folders fit

On Unraid, a shared folder shows the files of the SSD pool and of the array together. Tiering fits
a folder whose new files stay on the pool: **Primary storage: the pool, Secondary storage: none**
(shown as cache "Only" on older versions). For the others the page says why not:

- Unraid already moves all of the folder's files to the array each night (secondary storage is the
  array, mover direction pool to array).
- Unraid moves the folder's files back to the pool each night (mover direction array to pool).
- The folder is not kept on a pool.
- Unraid shows the folder straight from its pool ("exclusive access"), so files on the array would
  not appear in it. Turn exclusive access off for that share in Unraid.
- Kiboto cannot see the pool: its container needs the pool's path (for example `/mnt/cache`) as
  well as `/mnt/user`.
- The array has no drive the folder may use.

On another system that manages its own storage (TrueNAS, for example), a folder lives on one pool
only: there is no slower place for its files, and the page says so.

## On pools that Kiboto manages: a merged folder

Where Kiboto manages the pools itself (the Linux install), a shared folder lives on one pool. For
its old files to move to a slower pool and still show in the same folder, the folder becomes a
**merged folder** when you turn this on, and you choose the slower pool:

- its own files move to a hidden folder beside it on the same pool, `.kiboto-tier/<name>`. That is
  one rename: nothing is copied, and it takes a moment whatever the folder's size;
- the slower pool gets a hidden folder of the same name, `.kiboto-tier/<name>`, for the old files;
- at the folder's own path the two are shown as one. New files are written to the fast pool.

The folder is away for a few seconds while this happens. If the merge does not come up, Kiboto
puts the folder back exactly as it was.

The merge runs in a small container of its own (`kiboto-merge`), so restarting or updating Kiboto
does not interrupt it. While it is not running, the folder's path is an empty folder nobody can
write to and the page says that the two pools are not shown as one. **Nothing is lost then**: the
files are in the two hidden folders, and they show again as soon as the merge is back, which
Kiboto sees to when it starts.

What changes for a merged folder:

- **Snapshots** of it hold the files that are still on the fast pool. A file that has moved to the
  slower pool is not in snapshots taken after that.
- **A pool that holds one side cannot be removed, ejected or erased** while that is so.
- **Turning it off** stops the moving. The folder stays a merged one while files are on its slower
  side, so they keep showing; with nothing there, it becomes an ordinary folder again.
- A program of Kiboto's own that reads through the folder (a backup that reads every file) counts
  as someone opening the files here, because Kiboto cannot tell who asked the merge for a file.

It is not offered for a folder that is shared over NFS, nor for one that is mounted on its own (a
ZFS dataset): the page says which.

### The install file has to share mounts

What the merge mounts must be seen by Kiboto and by the container that serves SMB. Installs made
from the install file of 2.0.5 or later have this. On an older install, change two lines in
`docker-compose.linux.yml` and start the containers again (`docker compose up -d`). The line that
gives a service the storage, under `volumes:`, becomes this one, both in Kiboto's own service and
in the service whose container is `kiboto-samba`:

```yaml
      - ${STORAGE_POOL_PATH:-/mnt/storage}:/mnt/storage:rw,rslave
```

Until then the page says that the install file has to share mounts first, and offers no folder.

This part was tried with throwaway containers only (the merge seen from the host and from a second
container, a killed merge coming back, files moving between the two sides): there is no machine
with pools of Kiboto's own to try it on. To undo it by hand at any time: stop the `kiboto-merge`
container, remove the empty folder at the share's path, and move `.kiboto-tier/<name>` back to that
path; the old files are in `.kiboto-tier/<name>` on the slower pool.

## What Kiboto needs

- The app engine (Docker) reachable from Kiboto, to start the mover.
- The right to listen for file opens. Kiboto's own container has it on Unraid. Where it does not,
  the folder's line says that Kiboto cannot see which files are opened, and nothing moves.

## What it does not do

- It does not move files back to the fast pool.
- It does not move a file because the fast pool is full; only age counts.
- It does not touch a folder you did not turn it on for.
