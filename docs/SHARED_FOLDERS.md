# Shared folders

A shared folder is a folder your computers and phones open over the network: SMB for
Windows and Mac, NFS for Linux. **Settings → Shared folders** lists them, says who can open
each one, and how to connect.

## Sharing a folder

Sharing takes two steps: pick the folder, then choose who may open it. The folder must be
inside the storage folders; Kiboto refuses its own data folder and says why.

## Who can open it

Each person gets one of three levels per folder:

- **Can view and change**
- **Can view**
- **No access**

Administrators always open every folder, and everyone always has their own folder. On a NAS
where Kiboto runs the file sharing itself, this is **one list for Files and the network**:
what you choose here is what someone gets in the File Explorer and from their computer.

On Unraid or TrueNAS the host runs the network sharing. The page then says so: the list
applies to Files, and over the network the host decides.

## How to connect

Each folder's **How to connect** shows the address with a Copy button:

- **Windows**: map a network drive to `\\name.local\folder`. Where Kiboto serves the files itself
  (its own OS, or an install that runs Kiboto's file server) and **Find this NAS by name** is on,
  Windows PCs also list the NAS under **Network** in File Explorer. One service answers for
  that: the file server's own where it runs one, otherwise Kiboto's name service, which searches
  first and stays out when the box is listed already. On Unraid, Unraid's own service does that.
- **Mac**: in Finder, press ⌘K and enter `smb://name.local/folder`.

Where Kiboto serves the files itself, a shared folder and each private folder belong to the
file server's own user, and everyone who may open the folder reads and writes as that user. Who
may open it is what the folder's card says: the file server is told those names and lets nobody
else in. A change to who may open a folder counts at once: connections to that folder are closed
and connect again under the new settings, while other folders stay connected and a copy that is
running there goes on.

You sign in with your Kiboto user name and password. Someone with two-step sign-in uses a
separate password for network folders; they make it right there, on the folder's card.

## Backups from a Mac

A folder can take Time Machine backups from Macs (**Backups from a Mac**). It needs a size
limit, so the backups cannot fill the storage, and it is reached over SMB, so SMB stays on
for it. The page shows the steps on the Mac.

## Other ways to connect

Under **Other ways to connect**: WebDAV (for apps and phones that speak it) and SFTP (for
FileZilla, Cyberduck or a terminal), each with its own address and what it may open.

## Bring your files over from another NAS or a PC

Settings → Shared folders → **Copy from another NAS or PC**.

1. Say where the files are: another NAS or a PC (a Windows share), or a machine you reach with
   SSH. Give its address and an account there that can read the files.
2. Choose the folder there and the shared folder here. The folder arrives inside the shared
   folder under its own name.
3. **See what would be copied** compares both sides and writes nothing. Files that are already
   here with the same size and date are skipped.
4. **Copy now**. When it finishes, Kiboto compares both sides again; "Copied and checked" means
   nothing was left over. If files are missing, it says how many; **Copy again** fetches them.
5. **Forget the connection** removes the connection and its password from this NAS.

Nothing is changed or deleted on the other machine. A copy that stops (a cable, a sleeping PC)
keeps what it already copied; copying again goes on from there.
