# A second NAS that can take over (high availability)

Two Kiboto boxes at home can stand in for each other. The **first NAS** is the one the family
uses. The **second NAS** keeps a copy of chosen folders, people and settings, and takes over when
you press a button on it. Only the name the family uses for the NAS moves to the second one; going
back to the first is done by hand.

This is being built in steps. **What works today is the first step: pairing the two boxes**, with a
link between them that nobody else on your network can read. Keeping folders, people and settings
in step, and the takeover button, come with the next updates and will be described here.

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
