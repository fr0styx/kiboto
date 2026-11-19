# Kib

Kib is Kiboto's assistant. It reads the folders you choose and then finds files by what is
in them, and answers questions from them. **Kib runs on this NAS: your files and questions
stay here.** For how search works underneath, see [RAG.md](RAG.md).

Open Kib from the dock (or the **Ask Kib** tile on a phone). The Kib window has two tabs:
**Ask Kib** for questions and **AI search** for finding files and photos.

## Is Kib ready?

**Settings → Kib** starts with one line: Kib is ready (how many folders it may read, how many
files it knows), it is reading (you can keep asking), it is paused, it is waiting for a
drive to wake, or it needs a look.

## Which folders Kib reads

**Kib can read these folders** is a list with a tick box per folder. Tick the folders Kib
may read. If a drive is asleep, Kib reads that folder the next time the drive is awake:
Kib does not wake drives to read your files. Each folder's menu has **Read now**, **Stop
reading** (Kib keeps what it knows) and stop reading and forget the folder (your files
stay).

You can also choose the hours when Kib reads; outside them it still answers from what it
knows.

## Who can use Kib

**Who can use Kib** sets which roles may use it. The Kid and Guest roles cannot use the web.
Someone for whom Kib is off sees that before they type.

## How Kib answers

**Kib answers with**: **Automatic** (recommended: Kiboto picks the model that fits this NAS),
**Fast** (short answers, quickly), **Balanced** (good answers at reading speed) or **Best**.

## Asking about the NAS itself

Kib also answers from the NAS's own readings, taken at the moment you ask: how full each
storage pool is and whether the last check found damaged files, which drives are awake and
how warm they are, the fan profile, the apps that are running, the NAS's address, and how
much electricity it used (once a UPS measures it, see [POWER.md](POWER.md)). No drive is
woken for these answers. Ask in English, German, Spanish, French or Chinese: the question
reaches the same readings.

## Privacy

The Privacy section lists, from the real settings, what leaves the NAS and to which host,
if anything does (for example when you point Kib at a model on another computer). Web
lookups are off unless a chat turns them on, and that choice is not remembered.

Chats and Kib's index are encrypted when `KIBOTO_DATA_KEY` is set in the container settings;
the Privacy section says whether they are.

## Starting over

Under **Advanced**, **Forget everything and start over** makes Kib forget what it knows about
your files and read your folders again. Your files are not touched.
