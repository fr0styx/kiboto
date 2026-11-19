# Your own scripts

Kiboto can run a script of your own on a timer: copy a folder every night, tidy a downloads
folder each week, call a tool Kiboto has no button for. It is for the main administrator only
and it is **off until you turn it on**.

Open **Settings → Security → Your own scripts**.

## Turning it on

Press the switch and confirm. Until then nothing here runs, and "Run now" is refused. Turning
it off stops every schedule at once; your scripts are kept.

## Adding a script

Press **Add a script** and fill in:

- **Name**: how you will know it in the list and in the security log.
- **Script**: a shell script (bash). To use another language, start with a line such as
  `#!/usr/bin/env python3`. A script runs inside Kiboto, so it has what Kiboto's own system has:
  bash and the usual tools (`cp`, `mv`, `find`, `tar`, `gzip`), Python 3 and rclone. It cannot
  install programs that last: Kiboto's system is replaced with every update.
- **When it runs**: every hour, every day at a time, on some days of the week at a time, or only
  when you press **Run now**.
- **What it may change**: everything Kiboto can reach, or only one folder (see below).
- **Stop it after**: a time limit in minutes (30 unless you change it, at most 720). A script
  still running then is stopped, with everything it started.

Saving asks you to confirm: a script is a program with rights on your files.

A run that was due while the NAS was off is not made up for. A script meant for the night does
not start at breakfast.

## What a script can do

**Full rights.** The script runs with Kiboto's rights. It can read and change every file Kiboto
can: every shared folder, and Kiboto's own settings. Treat a script from someone else as you
would a program from someone else: read it before you save it.

**Only one folder.** The script can change files only in the folder you choose, and in a
scratch folder (`/tmp`) that is emptied when it ends. Everything else is read-only for it. It
can still read your other shared folders. It cannot see Kiboto's own settings and passwords,
cannot reach the drives themselves, cannot start or change your apps, and cannot give itself
the rights back. If Kiboto cannot set this up on your system, the option is greyed out, and a
limited script is not started rather than started without its limit.

A script can use the network either way.

## Seeing what happened

Each script shows when it last ran and how it ended. **Last runs** shows the last runs with the
end of what each printed (the last 16 KB; a script that prints for hours does not fill a
drive). The last 20 runs of each script are kept.

Every run is written to the security log (Activity → History, and "Save as a file" there):
which script, whether it ran on its schedule or who started it, how long it took and how it
ended. A scheduled run that ends with an error, runs past its time limit or could not be
limited to its folder also raises an alert, like other things that need a look.

## Limits

Up to 20 scripts, each up to 64 KB of text. Two scripts run at the same time at most; a third
that is due waits for its next time. One script never runs twice at once.

## An example

Keep only the last 30 days in a downloads folder, limited to that folder, every day at 04:00:

```sh
find . -type f -mtime +30 -delete
find . -mindepth 1 -type d -empty -delete
```

The script starts in its folder, so `.` is the folder you chose.
