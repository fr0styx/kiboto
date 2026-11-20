# Files

The **File Explorer** (Files in the dock) opens the folders you may use: your own folder and
the shared folders you have been given. Opening it doesn't wake sleeping drives.

## Seeing your files

List, Icon or Compact view, and the sort order, are remembered for you. Hidden files are
hidden by default; **Show hidden files** shows them (with a count of how many there are).
**Quick Look** previews a file without opening it; its Copy button copies the text, the
image or the path, whichever fits the file.

## Who owns what you make here

A file you upload, a folder you make, a copy and what comes out of an archive belong to the
folder they land in: they get that folder's owner and group. Where the folder lets its group or
everyone write, they may change the new file too. So what you put into a shared folder here can
be changed, renamed and deleted over the network share by the same people as everything else in
it. A file that only its owner may read keeps that when it is copied. The same goes for files
copied from another NAS or PC and for the folders the film and series tidy-up makes.

Files that arrive over **WebDAV or SFTP**, and files a **two-way sync** brings from the cloud,
stay the system's and get the shared folders' group and right to write. The people who may use
the folder can change them over the network share too.

A file you **move** keeps its owner, also when it goes to another drive.

What is **restored** is put back as it was: a file or folder from a snapshot keeps the owner it
has there, and an earlier version put back keeps the owner of the file it replaces.

Kiboto only does this for what it has just made. A file that was there before keeps its owner,
also one made here by an earlier version: those belong to the system, and can be read over the
network and not changed there. For those, open the folder's details, go to **Permissions** and
press **Give to this folder's people**: everything in the folder that still belongs to the system
gets the folder's owner. What belongs to someone else is not changed, and app folders are left
out. It works on a shared folder or a folder inside one, not above them (a drive's or pool's
top folder holds appdata and system, which stay the system's). It reads the whole folder, so on a large one it takes a while and wakes the drives it is on.

## Deleting and the Recycle Bin

Deleting moves a file to the **Recycle Bin** of its shared folder, where you can put it
back; it stays there for 30 days. A file larger than the bin keeps (a tenth of its drive) stays in the bin for one day,
then goes for good; Files says so before you delete it. **Empty Recycle Bin** deletes for
good. A bin on a sleeping drive is not shown, so the drive stays asleep; it appears once the
drive is awake.

When an upload has the same name as a file already there, **Replace** puts the old one in
the Recycle Bin and **Keep Both** keeps both.

## Earlier versions

**Previous versions…** on a file or folder lists the earlier versions the NAS kept.
**Restore a copy** puts the old version next to the current one; nothing is overwritten.

## Links

- **Share link**: a link to a file or folder for someone without an account, working for
  the time you choose or until you stop it.
- **Send me files**: a link others use to upload into one of your folders. The activity log
  notes each file that arrives.

## Tidying films and series

**Organize Media** sorts downloaded films and series into the folder layout Plex, Jellyfin
and Emby expect. It shows what it will do first.

## Labels

Right-click a file or folder and choose **Label…** to give it one of six colours. You can say what
a colour means to you ("Taxes", "To sort"); the name shows wherever the colour does. A coloured
dot marks the file in every view, and the sidebar lists the colours in use: click one to see
everything that carries it and jump to its folder.

Labels are your own: they are kept with your account, not in the files, so nothing on disk
changes and other people do not see them. Renaming or moving a file or folder in Files keeps its
label, and so do the labelled things inside a folder you move. A copy starts without one, and so
does anything that lands on a name already taken (merged into a folder that was there, or kept
under a second name). A label goes into the Recycle Bin with its file and comes back with it
when you restore it; once the bin has let the file go, the label is forgotten too.
