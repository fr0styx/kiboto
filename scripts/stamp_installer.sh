#!/bin/sh
# Writes the install script of a release to standard output: packaging/install.sh with the
# release's image written in by its digest, so that the script installs exactly that version.
#   sh scripts/stamp_installer.sh ghcr.io/fr0styx/kiboto@sha256:<digest>  > install.sh
set -eu
image=${1:-}
case "$image" in
  *@sha256:????????????????????????????????????????????????????????????????) ;;
  *) echo "give the image by its digest: name@sha256:<64 characters>" >&2; exit 2 ;;
esac
case "$image" in *[!A-Za-z0-9@:./_-]*) echo "that is not an image name" >&2; exit 2 ;; esac
here=$(dirname "$0")
src="$here/../packaging/install.sh"
[ "$(grep -c '^KIBOTO_IMAGE=""$' "$src")" = 1 ] || { echo "install.sh has no empty KIBOTO_IMAGE line" >&2; exit 1; }
sed "s|^KIBOTO_IMAGE=\"\"\$|KIBOTO_IMAGE=\"$image\"|" "$src"
