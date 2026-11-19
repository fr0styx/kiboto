# Network: is it fast enough?

Settings → Network answers two different questions.

## Speed between this device and the NAS

**Test the speed** measures the link between the device in your hand and the NAS: the browser
fetches test data from the NAS for up to 4 seconds, sends some back for up to 4 seconds, and
times five small requests. You get both directions in Mbit/s, the answer time, and one sentence
on what the slower direction is good for.

Nothing leaves your network (or, away from home, the connection you are already using), nothing
is stored, and every signed-in person may run it. A slow result at home nearly always means
Wi-Fi: move closer to the router or use a cable and test again.

## Speed of the internet line

**Test the internet line** measures your home's connection itself, from the NAS. It asks a
service outside your home (Cloudflare's speed test, which sees your home's internet address and
nothing else), so it is off until an administrator turns it on under Settings → Security →
Checks that use the internet. It runs only when you press the button and keeps the last result.

Which one do you need? Films stutter on the sofa but the NAS is at home: the first. Files load
slowly when you are away, or a cloud backup takes days: the second.
