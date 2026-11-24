# Kiboto threat model

What Kiboto protects, from whom, where the trust boundaries are, and which risks
remain. It describes the design as of the current main branch. Report gaps as in
[SECURITY.md](../SECURITY.md).

## What we protect

| Asset | Where it lives | Why it matters |
| ----- | -------------- | -------------- |
| Your files | Shares under the pool (`/mnt/user` on Unraid) | The reason the NAS exists |
| The host | Kiboto runs as root with disk, device and Docker access | Taking over Kiboto means taking over the server |
| Accounts and sessions | `data/users.db` (password hashes), session-signing key in `data/` | Lets someone act as you |
| AI index and chats | `data/rag_index.db`, `data/ai_conversations.db` | Contains excerpts of your files and what you asked |
| Secrets for integrations | Notification tokens, cloud remotes (rclone), API tokens | Reach other services in your name |

## Who we defend against

1. **Someone on the internet.** Kiboto is not meant to be exposed directly. Remote
   access goes through Tailscale or a reverse proxy with its own sign-in.
2. **Someone on your network**, including a compromised PC or IoT device: password
   guessing, cross-site requests from a page you visit, ransomware on a PC that has
   your shares mapped.
3. **A signed-in user with fewer rights** trying to reach other users' folders or admin
   functions.
4. **Content you index or download**: documents and web pages with instructions aimed at
   Ask Kib (prompt injection), malformed images and archives.
5. **A compromised update channel or third-party image.**

Out of scope: someone with physical access or root on the host, a compromised admin
account (it is root-equivalent by design, see below), and flaws in Docker, the kernel
or the apps you install.

## Trust boundaries and how each is defended

| Boundary | Defences |
| -------- | -------- |
| Browser → web app (port 8082) | Session cookie (HttpOnly, SameSite) or Bearer tokens; CSRF origin check on cookie writes; enforced Content-Security-Policy; must-change default password; login lockout and IP blocking (20 failures in 15 min); optional TOTP 2FA |
| Clients → WebDAV (8084) and SFTP | WebDAV: only Kiboto accounts and per-user share access; the portal has the account lockout and IP blocking, direct WebDAV on 8084 the account lockout only (it doesn't see the client's address). SFTP: its own accounts, made by an admin in the SFTP settings, with a password or a public key and a list of shares; they can't sign in to the web app |
| User → files | Every path is resolved inside the allowed roots (no `..` or symlink escape); non-admins reach only their home folder and shares they were given, at the level they were given |
| User → admin functions | Scoped permissions on every endpoint; root-equivalent permissions listed in SECURITY.md; destructive actions need confirmation |
| Web app → Docker | Allow-list proxy: no swarm, plugins, secrets, image build/import, commit or export; containers with host-level access only from confirmed flows, each logged |
| Web app → network (SSRF) | Outbound fetches for web search and previews only to public addresses; notification webhooks also to your own network (Home Assistant, Gotify), never to this machine or a cloud metadata address; catalog logos only from two fixed hosts, as raster images; AI runtimes only on this machine or its Docker network, never the LAN router |
| Indexed content → Ask Kib | File and web text is passed as quoted data, never as instructions; tools that change the system need your click on Confirm; web access only in chats where you turned it on; answers are limited to what your account may read |
| Alerts → phones (Web Push) | Encrypted per browser (RFC 8291) and signed with this NAS's VAPID key; the push service sees only ciphertext; only signed-in admins' devices subscribe |
| Update channel → host | The updater installs only images from this project's registry; images are signed (cosign) and scanned (Trivy) in CI, and promotion to Stable verifies the signature. The in-app updater verifies the image's Sigstore signature before installing it: issued to this repository's CI workflow (main or a version tag) and naming the exact digest (`UPDATE_SIGNATURES`, default enforce); data is snapshotted before each in-app update and can be rolled back |
| Files → shares (ransomware) | Ransomware guard: mass renames or deletes, ransomware extensions, ransom notes or a changed guard file freeze writes, snapshot where supported, block the source and alert |

## What remains

- **Kiboto is root on the host.** It needs raw disk, fan, LCD and VM access. A remote
  code execution bug in the web app is a host compromise. The Docker proxy narrows
  what a bug can do through Docker, but the web process is not yet separated from a
  privileged helper.
- **Admins are root-equivalent.** Anyone with container, VM, raw-storage or system
  configuration rights can gain root. Give those roles only to people you'd give the
  root password.
- **The local network is trusted for discovery.** SMB, NFS and WebDAV use passwords,
  but traffic on the LAN is only as private as your network unless you use SMB
  encryption or HTTPS through a reverse proxy.
- **Unraid's own shares are outside Kiboto's control.** The ransomware guard can only
  freeze Kiboto's own services there; use guard files for early warning and Unraid
  snapshots or backups for recovery.
- **Local AI models can still be misled.** Quoting and confirmation keep injected text
  from acting on its own, but a model can still give a wrong answer based on a planted
  document.

## A machine Kiboto runs (preview)

On a machine set up from Kiboto's install image or `install.sh` on Debian 13, Kiboto is the
machine's own service, not a container. What is above still holds; this is what changes.

| Boundary | Defences |
| -------- | -------- |
| Install image → machine | Debian's official netinst image, unchanged, checked against Debian's CD signing key before Kiboto's files are added; it asks for the system disk and touches no other disk |
| Release → machine | `install.sh` and every update install only an image signed by this project's CI for a version tag, named by its digest; a release is signed only after the owner approves it in CI, so a push to main alone cannot sign what such a machine installs. Anything else is removed again and nothing changes. An update is tried beside the running version and goes back by itself when the new one does not stay healthy |
| First sign-in | A one-time code on the machine's screen and SSH greeting, in files only root can read, removed once the admin chooses a password |
| Network → shared folders | The machine's own Samba and NFS serve the folders; each person signs in to their private folder as their own system account. Failed SMB sign-ins count toward the block list like web ones (20 in 15 minutes block the address for an hour); blocked addresses are in Samba's `hosts deny` |
| Account names → system tools | A Kiboto username that would read as an option (starting with a dash) never reaches `useradd`, `userdel` or `smbpasswd` |
| System disk → your data | Shared folders, home folders, apps and virtual machines are kept on the pools, never on the system disk; an encrypted copy of the settings on every pool brings the same Kiboto back on a new system disk with its recovery key |
| AI data at rest | Always encrypted, with a key sealed to the machine's TPM where it has one |

What remains on such a machine:

- **The web process runs as the unprivileged user `kiboto`** (ADR 0006). Everything it does as
  root on the machine goes through the host door: a separate root service that takes only a fixed
  list of operations, checks each one's arguments and logs it to `door-audit.log`. Root can run it
  as root again (`python -m backend.services.web_user off` in `/opt/kiboto/current`); that choice
  is kept across updates. Anyone who takes over the web process can still ask the door for what
  the door allows, and for every file the user `kiboto` may open.
- **Debian's packages are updated by Debian.** Kiboto holds the kernel, ZFS and Docker at the
  versions it was tested with; everything else follows Debian's own security updates, which the
  machine installs only when someone runs them.
- **Physical access is trusted.** Whoever is at the machine sees the first-time code until a
  password is chosen and can boot another system.

## Reviewing changes against this model

A change needs a second look when it adds an endpoint without a scope, reads a path
from a request without `resolve_within`, fetches a URL from user input, starts a
process or container, adds a Docker API call, or gives the AI a new tool. The test
suite checks several of these: every Docker call against the proxy allow-list, every
AI tool against the permission registry, and path traversal for the file APIs.
