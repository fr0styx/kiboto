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

- **Windows**: map a network drive to `\\name.local\folder`.
- **Mac**: in Finder, press ⌘K and enter `smb://name.local/folder`.

You sign in with your Kiboto user name and password. Someone with two-step sign-in uses a
separate password for network folders; they make it right there, on the folder's card.

## Backups from a Mac

A folder can take Time Machine backups from Macs (**Backups from a Mac**). It needs a size
limit, so the backups cannot fill the storage, and it is reached over SMB, so SMB stays on
for it. The page shows the steps on the Mac.

## Other ways to connect

Under **Other ways to connect**: WebDAV (for apps and phones that speak it) and SFTP (for
FileZilla, Cyberduck or a terminal), each with its own address and what it may open.
