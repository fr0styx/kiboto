# ADR 0007: The family portal, a public way in for people who can't install an app

- **Status:** Accepted (the owner's decision D12 part 2, 10 Nov 2026: opt-in; a person's own files and photos only, never the admin pages; passkey sign-in required)
- **Progress:** step 1 (the portal's own sessions, sign-in by passkey, the join link, reading files) built; step 2 (publishing it through Funnel and the owner's card) and step 3 (the page) to come
- **Date:** 2026-11-25
- **Decides:** how part of Kiboto is reachable from the internet for family members, and what stops it from being more than that

## Context

The guided invite (NFEAT-1, b568924) gives each family member a way in through Tailscale: they
install its app and accept a share of the NAS. Some people can't or won't install an app (a
grandparent's tablet, a work laptop). For them the owner chose an opt-in public portal: their
files and photos in a browser, from anywhere, and nothing else.

Putting any of Kiboto on the internet is the riskiest thing it does. The web interface has
hundreds of routes written for the home network and the tailnet; none of them may become public
by accident. The share links already show the pattern that works: Tailscale Funnel publishes one
path (`/api/fs/shared`) on its own port (8443), and nothing else of Kiboto is reachable that way.

## Decision

1. **One path, one port.** The portal lives under `/portal` and is published with Funnel on the
   share links' port, 8443 (`tailscale funnel --set-path=/portal`). Funnel forwards only that
   path; the rest of Kiboto, the admin pages and `/api` included, stays unreachable from outside.
   Everything the portal needs (its page, its script, its API) is under `/portal`.
2. **Its own sessions, useless anywhere else.** A portal sign-in gives a `zpt_` token in a cookie
   of its own (`kiboto_portal`, `Path=/portal`, HttpOnly, Secure, SameSite=Strict). The main API
   refuses `zpt_` tokens outright, as it refuses console tickets (`backend.auth.get_current_session`
   returns None). Portal sessions end after 30 minutes without use and after 12 hours at most; a
   person taken off the portal, disabled or deleted loses them at once.
3. **Passkeys only.** No password is typed into the portal: sign-in is a passkey made on the
   portal's own address (its relying party id is the NAS's Tailscale name). A person gets one by a
   single-use join link the owner makes for them (7 days): it opens a page on the portal that
   registers a passkey for that one account, and then signs them in. Failed sign-ins count per
   address; the join link counts its tries.
4. **The person's own files, whatever their role.** Every portal request reads through the same
   rule as a family account in the Files app (`path_access.check_user_path_access`): their home
   folder and the shared folders granted to them. The portal builds that check with no admin
   scopes, so an administrator sees only their own files there too: never `appdata`, another
   person's home, a pool root's content or a system folder. Step 1 reads only (list, thumbnails,
   download); uploading to one's own Inbox may come later.
5. **Off until the owner turns it on, and per person.** The portal answers only while it is on and
   only for people the owner allowed. Turning it on is confirmed and recorded in the security log.
   The security advisor names it while it is on.

## Consequences

- A bug in any ordinary route can't be reached from the internet through the portal: Funnel
  doesn't forward it, and a portal session isn't accepted there.
- A bug in the portal's own routes can be: they are few, kept small, and tested for confinement
  (another person's home, `..`, symlinks out, an admin's portal session, a `zpt_` token on `/api`).
- Passkeys made on the home network don't work on the portal (another relying party id); a
  passkey made on the NAS's Tailscale address does, since the portal shares that name.
- Big downloads go through Tailscale's relays and are slower than at home, as share links are.

## Not chosen

- **Publishing the whole interface behind a login.** Every route would become public; one missing
  check anywhere would be enough.
- **Passwords on the portal.** Passwords are phished and guessed; the owner asked for passkeys.
- **A second web server.** Funnel's path forwarding already gives the one-path boundary, and a
  second server would duplicate the folder rules.
