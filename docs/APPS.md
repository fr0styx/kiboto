# Apps

Apps are programs that run beside Kiboto on your NAS: a media server, a photo library, a
password manager. Each runs in its own container. Kiboto installs them, keeps them up to
date, backs them up and removes them, and it never leaves an app half changed.

Open **Apps** from the dock. The list shows one row per app, with its state in words and
an **Open** button when the app has a web page. **⋯** holds everything else. To see the
containers, ports and Compose files behind each app, switch on **Show Docker details**
(remembered per person).

## Getting apps

**Get apps** lists the catalog that ships with Kiboto. Search first, then **Install**.
Catalog apps install at the exact version this Kiboto release was tested with (the image is
pinned to its digest), so two installs of the same Kiboto get the same app.

To run something that is not in the catalog, use **Add your own app** and paste a
Docker Compose file. Kiboto shows what it will create before anything starts. The name
must be lower-case letters, digits, `-` or `_`; the app's files live in
`appdata/<name>`.

## Updates

- **Catalog apps** offer an update when a Kiboto release ships a newer version that was
  tested with it. A new upload by the app's maker alone is not an update.
- **Apps you added yourself** are checked against their own source when you press
  **Check for updates**.

An update never leaves an app broken. The old version stays until the new one has kept
running for 15 seconds (or until its own health check says it is healthy). If the new
version crashes, stops or reports itself unhealthy, the old one comes back, and Kiboto
tells you what happened.

An app made of several parts (for example a web app and its database) is updated part by
part, in the order they start. If one part fails, the parts already updated go back to
their old versions as well, so the app never runs half updated. Each part's old container
stays (stopped) until every part runs on its new version.

## Changing an app's Compose file

With **Show Docker details** on, **Apply** a changed Compose file to an app. Kiboto
shows what will change, keeps the old file, and replaces only the parts whose settings
changed. A part counts as started when it keeps running for 5 seconds (or reports
healthy); a part that exits or keeps restarting sends the whole app back to how it was.

## Back up, restore, remove

- **Back up** makes one archive of the whole app: every part's settings, the Compose file
  Kiboto rebuilt from them (including each part's command), and the app's folders.
  Archives are kept in `appdata/.backups/<app>`.
- **Remove** takes a backup first and then removes every part, the last started first.
  If the backup fails, nothing is removed.
- **Restore** brings a removed app back from its backup: files first, then the app is
  started again with the same apply as above.

## What Kiboto will not do

- Change its own container from inside the app (update Kiboto from **Settings → General**).
- Remove a stopped app during clean-up unless you tick it; the clean-up names each app.
- Give an app new access to the host (devices, host network, privileged mode) when it
  applies a Compose file or changes an app, without asking you first.
