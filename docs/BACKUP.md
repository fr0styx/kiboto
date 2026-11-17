# Backup

**Settings → Backup** answers one question first: **are your files safe?** — Fine, Needs a
look, Failed, or Not protected yet — with when and where the newest copy outside this
Kiboto was made. A copy on the same disks as your files does not count: a failed disk, a
theft or a fire would take both.

To back up your computers *to* Kiboto, see [BACKUP_GUIDE.md](BACKUP_GUIDE.md).

## Your folders and their copies

The list shows every folder and what copies it: copied (and when), partly copied, or no
copy outside this NAS. A folder you never want copied (downloads, a cache) can be **left out
on purpose**, so it stops counting as unprotected.

## Adding a copy

**Add a copy** makes an off-site backup: to a USB disk, another NAS, or the cloud. Earlier
versions are kept and the copy is encrypted. When a large empty USB disk is plugged in,
Kiboto offers it for backups in one step (or, if you choose, backs up to it by itself
whenever it is plugged in).

A copy that was missed for more than a day (the NAS was off, the other side did not
answer) is caught up instead of waiting for the next scheduled day; a failed one is tried
again once an hour.

## Getting a file back

**Restore** on the Backup page (or **Get a file back** in Spotlight) leads to the earlier
versions of a file or folder. **Restore a copy** puts the old version next to the current
one; nothing is overwritten.

## Kiboto's own settings

A **settings backup** keeps people, shared folders, apps and their settings, encrypted
with a passphrase, so a new Kiboto can start where this one was. Your files themselves are
copied by **Add a copy**. To start a new Kiboto from one, see "Recover on new hardware" in
[BACKUP_GUIDE.md](BACKUP_GUIDE.md).
