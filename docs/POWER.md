# Power

**Settings → Power** (under Advanced) answers one question first: what happens to the NAS
when the power goes out. Everything else on the page follows from that answer.

## When the power goes out

With a UPS connected, Kiboto watches it and shuts the NAS down safely before the battery
runs out: virtual machines are asked to shut down first, then the host shuts down. You set
when: when the UPS estimates this many minutes are left or the charge drops this low, and if
you like also after a fixed time on battery. **Check that it works** walks through what Kiboto can see of your UPS without
switching anything off.

The **history** says in sentences what happened at each outage: when the power went, when
the NAS shut down, when it came back.

## Coming back by itself

A NAS only starts again on its own when two things are true:

1. Its BIOS is set to switch on when power returns ("Restore on AC power loss").
2. The UPS switches its sockets back on when the mains returns.

For the second, Kiboto asks the UPS for `shutdown.return` at the end of a safe shutdown:
sockets off after a delay, back on when the power is back. Only a UPS reached over the
network (NUT) takes commands; **Check that it works** says whether yours has that command.

After the first real power cut, the next start asks you one question: did the NAS come back
by itself? Your answer is kept, and the page then says "proven" (or what to look at).

## Restart and Shut down

The buttons are on the Power page and in the menu behind your name. Running virtual
machines are asked to shut down first; everyone using the NAS loses their connection until
it is back.

Kiboto only offers them when it has a command that really reaches the host, and says why
not otherwise:

- **Kiboto's own OS images** and installs directly on the host: they work.
- **Kiboto in a container** (for example on Unraid): the host's own command has to be
  available at `/host/reboot` and `/host/powerdown`, or Unraid's `/usr/local/sbin` commands.
  Until then, use the host's own menu; the page says so.

## Switch off at night

Kiboto can switch the NAS off at night and wake it in the morning, on the nights you
choose. Waking needs the board's wake-up clock (`/sys/class/rtc/rtc0/wakealarm`); when
Kiboto cannot set it, it refuses to switch off, because the NAS would not come back by
itself. The activity log notes each night's switch-off and the wake time.
