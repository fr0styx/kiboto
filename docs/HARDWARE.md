# Hardware

**Settings → Hardware** (under Advanced) is about the box itself: how the fans cool it, the
light bar and the front screen. Most homes never need it: the fans follow the drives'
temperature on their own.

## Cooling

**Automatic** follows the temperature and is the one to keep. The other choices trade noise
for cooling. Whatever you choose, the fans run at full speed when a hard drive reaches 55 °C,
an NVMe drive 75 °C or the processor 80 °C.

## Quieter at night

Off until you turn it on. In Automatic, between two times (23:00 to 07:00 unless you change
them), the drive fans act as if the drives were 4 °C cooler, so they turn a little slower while
the household sleeps.

- From 45 °C the difference shrinks, and from 50 °C the fans follow the normal curve again: a
  warm drive is never kept quiet.
- The full-speed limits above still apply, and the processor and NVMe fans are not changed.
- Fixed fan speeds are not affected; it only acts in Automatic.

The card says when it is on and when it is quieter right now.

## Where the facts about your NAS are

The Hardware page used to list them all; they are now where you would look for them:

- Processor, mainboard, BIOS, graphics and the system version: **Settings → General → About →
  Technical details**.
- The array's state, drives, parity check and mover: **Storage → Pools → Storage details**.
- The AI chip: **Kib → Advanced**.
- The load: **Activity → Right now**.
