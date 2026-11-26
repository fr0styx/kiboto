# Releasing Kiboto

Every release spends three days on the **beta** channel before it reaches **stable**
(OPS-07). Stable users get exactly the image beta users ran: promotion moves tags to the
same signed digest, it never rebuilds.

**Stable is a weekly train** (COMP-10): every Tuesday the newest beta that has had its three
days becomes Stable, so stable users get at most one update a week with one set of dated
notes. Security fixes don't wait for the train (see below).

| Image tag | What it is | Who gets it |
|---|---|---|
| `:edge`, `:main` | every commit on `main` that passes CI | `UPDATE_CHANNEL=edge` |
| `:beta`, `:2.0.7` | the newest version tag, from the moment CI passes | `UPDATE_CHANNEL=beta` |
| `:latest`, `:stable`, `:2.0` | the newest release that finished its soak | `UPDATE_CHANNEL=stable` (default) and Compose files that pin `:latest` |

Each tag also exists with `-core` for the core image.

## Version numbers and changelog entries

- **A release bundles a couple of days of commits**, never a single one: commits land on main
  (and on test servers) as they are ready, and a release is cut once a few days of them have
  piled up.
- **Each release bumps the patch number** (2.0.0 → 2.0.1 → 2.0.2), features included. A minor
  or major number changes only when the maintainer decides to mark a bigger step.
- Anything users must act on (a stricter default, a removed option, a changed URL or API) is
  listed under "Before you upgrade" in the changelog entry, whatever the number.
- **Changelog headings** are `## vX.Y.Z (date)`, without a channel. A release is a beta
  until promotion marks it Stable on GitHub; the changelog doesn't change when it is
  promoted. A test checks this for entries after v1.9.4.

## Cutting a release

1. Refresh the app catalog's image pins (`python scripts/pin_catalog_images.py`, which writes
   `backend/services/catalog_digests.json`), then update `CHANGELOG.md` and the version, commit, and push a tag such as `v2.0.7`. Only
   repository admins can create `v*` tags, and tags can't be moved or deleted (GitHub
   rulesets).
2. CI builds, scans and tests the images, and installs Kiboto OS from the build in a fresh
   Debian 13 virtual machine (`scripts/os_install_check.sh`, which also runs by hand: Actions,
   **Kiboto OS install check**, with a build's digest). Then it waits for the owner's approval (the `release`
   environment: Actions, the run, **Review deployments**). Once approved it signs them for the
   tag and publishes `:beta` and `:2.0.7`. The GitHub release is created as a pre-release named
   "… (beta)". A machine Kiboto runs installs only images signed for a version tag, so a push
   to main alone cannot sign what it installs (`KIBOTO_ACCEPT_MAIN_BUILDS=1` lets a test machine
   take main builds).
3. Run the beta on a real server (Mission Control → Settings → About & Updates → Beta, or
   `UPDATE_CHANNEL=beta`).
4. Every Tuesday (06:00 UTC), the **Promote release** workflow takes the
   newest release that is at least three days old, verifies its image signature, moves
   `:latest`, `:stable` and `:2.0` to it, and marks the GitHub release as the latest, so the
   app's Stable channel offers it. On other days the scheduled run only names the next train
   date in its summary. It warns when nothing has reached Stable for 21 days.

## The lowest version Kiboto OS installs

`LOWEST_VERSION` in `backend/services/native_update.py` is the oldest version a Kiboto OS machine
installs as an update; the root service reads the version from inside the downloaded image. When a
release fixes something in the root service, raise it to that release's version in the release
commit, so no machine can be talked into installing the version with the bug again. It may never be
higher than the version being released (a test checks). Revert, which goes back to a version kept on
the machine, is not limited by it.

## What a release carries

Beside the images, the GitHub release has `install.sh` (the install script for a machine of its
own, naming this release's image by its digest), the install image `kiboto-vX.Y.Z-install.iso`,
and `SHA256SUMS` with its signature for both. The release job's last step asks the release
whether the install image is there. If it is not (Debian's servers were down, or the upload
failed), the release stays, because the container does not need the image, but the job is red:
run that job again, and it builds and attaches the image.

## Stopping a release

Set the repository variable `HOLD_RELEASES` (Settings > Secrets and variables > Actions >
Variables) to the version, for example `v2.0.7`, or to `all`. Promotion skips it and says so
in the workflow summary. Remove the variable to let it continue; fix forward with a new tag.

## Withdrawing a bad release

Tags cannot be moved or deleted, and promotion only goes forward, so a bad release is withdrawn by
pointing the channels back at the release before it and fixing forward. Every image keeps its
signature: moving a tag to an older digest needs no new signing, and Kiboto checks the digest it is
given. `vBAD` is the bad release, `vGOOD` the one before it; run the image commands for both
images (`ghcr.io/fr0styx/kiboto` and, until 2.2, the name from before the rebrand, `OLD_IMAGE_REPO` in
`backend/legacy_names.py`) and both
variants (no suffix and `-core`).

1. **Stop it going further.** Set the repository variable `HOLD_RELEASES` to `vBAD` (see above),
   so promotion skips it.
2. **Point the channel back.** Find the good digest and move the channel's tag to it:

   ```bash
   docker buildx imagetools inspect ghcr.io/fr0styx/kiboto:GOOD --format '{{json .Manifest}}' | jq -r .digest
   docker buildx imagetools create -t ghcr.io/fr0styx/kiboto:beta ghcr.io/fr0styx/kiboto@sha256:<good digest>
   ```

   For a release that already reached Stable, move `:latest`, `:stable` and `:MAJOR.MINOR` the same
   way, and make the good release the latest on GitHub again:
   `gh release edit vGOOD --latest` and `gh release edit vBAD --prerelease`.
3. **Say so.** Begin the bad release's title on GitHub with "Withdrawn:" and say why in its notes;
   take its install image off the release page (`gh release delete-asset vBAD kiboto-vBAD-install.iso`).
4. **Fix forward** with the next patch version. If the bad release has a bug in the root service,
   raise `LOWEST_VERSION` to the fixed version in that release, so no Kiboto OS machine can be
   asked to install the bad one again.

Machines that already updated stay on the bad version until the fixed one reaches their channel.
Revert, in the app, takes one back to the version it had before the last update.

## Skipping the wait (security fixes)

Actions > **Promote release** > Run workflow: enter the version and tick **skip_soak**. The
same checks run (signature, hold), just without the three days.
