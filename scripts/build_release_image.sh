#!/bin/sh
# Builds Kiboto's install image for a release, from Debian's current official netinst image:
#
#   sh scripts/build_release_image.sh <kiboto image>@sha256:<digest> <out.iso>
#
# Debian's checksum file is checked against Debian's CD signing key (its fingerprint is pinned here,
# from https://www.debian.org/CD/verify), and the netinst image against that checksum file, before
# anything is built from it. Needs curl, gpg and xorriso.
set -eu
image=$1 out=$2
case $out in /*) ;; *) out=$PWD/$out ;; esac  # written here, not in the work folder deleted at the end
BASE=https://cdimage.debian.org/debian-cd/current/amd64/iso-cd
DEBIAN_CD_KEY=DF9B9C49EAA9298432589D76DA87E80D6294BE9B  # Debian CD signing key, a public fingerprint gitleaks:allow
here=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cd "$work"
curl -fsSL -o SHA256SUMS "$BASE/SHA256SUMS"
curl -fsSL -o SHA256SUMS.sign "$BASE/SHA256SUMS.sign"
export GNUPGHOME="$work/gnupg"
mkdir -m 700 "$GNUPGHOME"
gpg -q --keyserver hkps://keyring.debian.org --recv-keys "$DEBIAN_CD_KEY"
gpg -q --status-fd 1 --verify SHA256SUMS.sign SHA256SUMS 2>/dev/null | grep -q "VALIDSIG $DEBIAN_CD_KEY" \
  || { echo "Debian's checksum file is not signed by the Debian CD key" >&2; exit 1; }
name=$(grep -oE 'debian-13\.[0-9]+\.[0-9]+-amd64-netinst\.iso' SHA256SUMS | head -1)
[ -n "$name" ] || { echo "no Debian 13 netinst image is listed" >&2; exit 1; }
curl -fsSL -o "$name" "$BASE/$name"
grep " $name\$" SHA256SUMS | sha256sum -c --quiet
sh "$here/packaging/image/build-image.sh" "$work/$name" "$image" "$out"
echo "built $out from $name"
