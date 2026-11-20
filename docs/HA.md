# A second NAS that can take over (high availability)

Two Kiboto boxes at home can stand in for each other. The **first NAS** is the one the family
uses. The **second NAS** keeps a copy of chosen folders, people and settings, and takes over when
you press a button on it. Only the name the family uses for the NAS moves to the second one; going
back to the first is done by hand.

Pairing, the copy of people and settings, the folders kept in step and the takeover are all
described below. Two things happen by themselves: the nightly fetch on the second NAS, and a
first NAS keeping quiet about its name when it finds that the second one took over. Taking over
and going back are buttons you press.

## Pairing the two boxes

Both boxes need Kiboto and have to be on your home network (or both on Tailscale). Someone who may
change the system does this, on **Backup → A second NAS that can take over**.

1. On the first NAS choose **This is the first NAS: show a pairing key**. A key of 16 signs is
   shown. It is good for 10 minutes and for one pairing, and it is shown only then.
2. On the second NAS choose **This is the second NAS: pair with the first**. Give it the first
   NAS's address, the pairing key, and its own address (where the first NAS reaches it), and
   confirm.
3. Both cards now say which part the box has and who the other one is. **Check now** asks the
   other box whether it is there.

The addresses are number addresses, like `http://192.168.1.20:8082`: an address on your home
network or on Tailscale (a `.ts.net` name works too). Kiboto does not look names up for this, and
it refuses an address on the internet.

After 5 tries with a wrong pairing key the key is gone; make a new one.

**Unpair** on either box ends it and tells the other box, if it can be reached. A box that could not
be told keeps its part until it is unpaired there too.

## The copy of people and settings

Once paired, the second NAS asks the first for its people and settings: right away, then every
night at 02:30, and when you press **Fetch now** on the second NAS's card. What it gets is the same
encrypted settings backup the Backup page makes: the people with their sign-ins and two-step
sign-in, the settings, the shares, the apps' definitions, and the key the sealed parts need. It
does not hold your files.

The second NAS **keeps this copy and does nothing with it**. Its own people and settings stay as
they are until the day it takes over; a mistake made on the first NAS is not carried over at once.
The copy is kept encrypted, and what opens it is sealed with the second NAS's own key. Each fetch
replaces the copy before. Unpairing removes it.

The card on the second NAS says from when its copy is; the card on the first says when the second
last fetched.

## The folders

On the second NAS's card, tick the first NAS's shared folders that the second one should keep.
They are fetched right away, then every night after people and settings, and when you press
**Fetch now**. Each folder lands in a **shared folder of the same name** on the second NAS; one
that is not there yet is made (where this system's shared folders are Kiboto's to make; otherwise
the card asks you to make it).

- Only files that are new or changed travel. A file's date, and who may read it, come along.
- **A file deleted on the first NAS is kept on the second for 30 days**, in the hidden folder
  `.kiboto-removed` inside the share, under the day it was put away. Then it goes.
- **The second NAS never touches files of its own.** It only replaces or puts away files it
  fetched itself and that nobody changed there since. A file of the second NAS's own under the
  same name stays as it is, and the card counts it.
- Links are not followed and not copied. At most 20 folders, and 1000000 files in one.
- When the second NAS is full the fetch stops and says so; what it has stays.
- Fetching wakes the drives of both boxes: the first one's to read, the second one's to write.

Everything travels through the encrypted link in pieces, which is slower than a plain copy over
the network. The first fetch of a large folder can take many hours; the nightly ones only carry
what changed.

Unpairing forgets which folders were chosen. The copies themselves stay where they are.

## Taking over

On the **second NAS**, **Take over now** makes it the box the family uses. It is for the day the
first NAS is broken, stolen or being repaired. It asks you to confirm, then:

1. It asks the first NAS whether it is there. While the first NAS still answers, the takeover is
   refused: two boxes would answer to one name. Turn the first NAS off and try again. If you know
   it answers and want to go ahead (it is about to be unplugged), **Take over although it answers**
   does it; the first NAS is told and stops answering to the name at once.
2. It takes the first NAS's **people** out of the kept copy: their accounts, passwords, roles and
   two-factor (everyone keeps the authenticator app they have), and their sign-in for shared
   folders over the network. For the folders kept in step it also takes **who may open them**.
   The people the second NAS had before are replaced; they are saved first, as before any
   settings restore.
3. It takes the **name** the family types (for example `kiboto.local`), when the first NAS was
   answering to one. Its old name still works too.
4. It restarts, and you sign in with an account of the first NAS.

What the second NAS keeps of its own: its network address, its drives and their settings, its
apps, virtual machines and backup jobs. Those belong to the hardware, and the first NAS's copies
of them are not applied. Apps do not move: install on the second NAS the ones you need.

### What else can come along

Under the button there is a box to tick: **Also bring the first NAS's backups, switched off.**
It is a choice because a backup acts by itself once it runs: a copy job that mirrors makes its
destination look like the folder it copies. So what comes along arrives **switched off**, and you
turn each one on under Backup after a look.

- A **copy job** comes along when its folder is one of the folders kept in step here. It is
  pointed at this NAS's folder of that name.
- An **off-site backup** comes along when it backs up such folders; its paths are pointed at the
  folders here, its hour is cleared, and its recovery key comes with it. The backups already at
  the destination stay as they are and can be restored from here.
- The **cloud sign-in** a backup needs comes with it. If this NAS already has a different
  sign-in of the same name, that one is not replaced and the backup stays behind.
- **Stays behind:** a backup onto a drive of the first NAS, a job for a folder this NAS does not
  keep, and the backup of the first NAS's own settings.

Passwords that the first NAS kept sealed are sealed again with this NAS's own key. After the
takeover the card says how many backups came along and how many stayed behind.

### The apps

An app is not a setting: its set-up lives in Docker on the first NAS, and its files in a folder.
So with every fetch the first NAS also tells the second one how each of its apps is set up (a
Compose file rebuilt from the app's containers). The second NAS keeps that sealed, because a
set-up holds the app's passwords, and does nothing with it. Kiboto itself is never in the list.

After a takeover the card lists **Apps of the first NAS**. **Add here** on one sets it up on
this NAS and starts it, after you confirm. It is your choice app by app:

- An app **can be added** when every folder it uses is inside a folder kept in step. It is then
  pointed at this NAS's copy of that folder. Keep the folder the apps store their files in (often
  `appdata`) in step if you want apps to follow.
- An app whose files are in a folder that is **not kept here** cannot be added, and the card
  names the folder. Nothing is set up empty.
- The files are **last night's**. A database that was being written while it was copied may
  need the app's own repair.
- If a part of the app does not come up, everything is **taken back**, and the card says why.
- An app that asks for **host-level access** (for example a privileged container) is not added
  from here. Add it under Apps if you want it; that is a decision for a person.
- Images are downloaded when an app is added, so the second NAS needs the internet for it.

Apps added this way are this NAS's own afterwards: taking the name back or unpairing leaves
them where they are.

After a takeover the second NAS fetches nothing more from the first one. The folders hold what
the last nightly fetch brought, so at worst a day of changes is missing.

## When the first NAS comes back

Before it answers to its name at start, the first NAS asks the second one. If the second one
took over, the first NAS **holds its name back**: it runs, you can reach it at its number
address, and it does not announce the name. It asks again every quarter of an hour, so a first
NAS that was started while the second one was off notices later.

**Take the name back** on the first NAS ends this: the second NAS stops answering to the name and
is called what it was called before, and the first NAS answers again. If the second NAS cannot
be told, the button is refused, and **Take it back anyway** goes ahead; turn the second NAS off
or unpair it, or two boxes answer to one name.

Going back is done by hand: **files and people changed on the second NAS while it
stood in are not copied back by themselves.** Copy the changed files to the first NAS (the
second one's shared folders hold them), and make account changes again on the first NAS. After
that the second NAS is the second NAS again and fetches every night; files it changed itself are
its own and are left alone by the fetch.

Unpairing ends all of it: neither box holds anything for the other, and each keeps the name it
has at that moment.

## How the link is protected

The two boxes may talk over a plain home network, so the link brings its own encryption and does
not depend on Tailscale or on a certificate:

- The pairing key is 80 random bits. Each box makes a fresh key pair and proves with the pairing key
  that its public half is its own. Someone on the network in between who does not have the pairing
  key can neither read what follows nor put themselves in the middle.
- From the two key pairs both boxes work out the same key without it ever being sent. It is kept
  sealed on each box.
- Every message afterwards is encrypted with that key (AES-256-GCM), names its sender and its
  receiver, carries the time, and is accepted once: a message that was changed, sent again, kept
  for later or meant for another box is refused. An answer only counts for the question it
  belongs to.
- The two routes the other box calls need no sign-in, and give nothing to anyone without the
  pairing key or the shared key. They are limited to a number of tries a minute.

The clocks of the two boxes must agree to within 2 minutes; if they do not, the card says so.
