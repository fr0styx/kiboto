#!/bin/sh
# Kiboto on a machine of its own: turns a fresh, minimal Debian 13 into a Kiboto-managed host.
#
#   sh install.sh                                         install the version this script was released with
#   sh install.sh --image <image>@sha256:<digest>         install that published version
#   sh install.sh --from <folder with Kiboto's code>      install from a folder (for development)
#   sh install.sh --uninstall [--purge]                   take Kiboto off again (--purge: its settings too)
#
# Debian keeps doing what it does: boot, drivers, and its own updates through apt, which stays yours
# to use. Kiboto adds its service, the storage and sharing tools it drives, and Docker for apps.
# Three things are held at the version Kiboto was tested with and move only with a Kiboto update:
# the kernel, ZFS and Docker (`apt-mark showhold` lists them; `apt-mark unhold` gives them back).
# Storage pools and what is on them are never touched by this script, in either direction.
set -eu

# The version this script installs when it is given none: written in when a version is released,
# with its digest, so what is installed is exactly what the release named.
KIBOTO_IMAGE=""
PREFIX=/opt/kiboto
DATA=/var/lib/kiboto
ETC=/etc/kiboto
HELD="linux-image-amd64 linux-headers-amd64 zfs-dkms zfsutils-linux docker.io"
# what Kiboto drives: disks and SMART, the three kinds of pool, sharing, apps, virtual machines
TOOLS="smartmontools nvme-cli sg3-utils usbutils btrfs-progs e2fsprogs parted gdisk fuse3 gocryptfs mergerfs \
rclone restic samba nfs-kernel-server docker.io docker-cli qemu-system-x86 qemu-utils ovmf swtpm \
systemd-timesyncd libtss2-esys-3.0.2-0t64 libtss2-rc0t64 libtss2-mu-4.0.1-0t64 \
python3-venv ca-certificates curl"

say() { printf '%s\n' "$*"; }
die() { printf 'Kiboto was not installed: %s\n' "$*" >&2; exit 1; }

must_be_this_machine() {
  [ "$(id -u)" = 0 ] || die "run this as root."
  [ -f /etc/os-release ] || die "this is not a Debian system."
  . /etc/os-release
  [ "${ID:-}" = debian ] && [ "${VERSION_ID:-}" = 13 ] || die "this is ${PRETTY_NAME:-not Debian 13}; Kiboto is installed on Debian 13."
  [ "$(dpkg --print-architecture)" = amd64 ] || die "this machine is not a 64-bit PC (amd64)."
  [ ! -e /.dockerenv ] && [ ! -e /run/.containerenv ] || die "this is a container; Kiboto needs the machine itself."
  command -v systemctl >/dev/null || die "systemd is not running here."
}

# A machine that already serves files or runs containers has settings Kiboto would write over.
must_be_fresh() {
  [ -e "$ETC/managed" ] && return 0   # Kiboto's own earlier install: this run updates it
  if [ -s /etc/samba/smb.conf ] && dpkg -s samba >/dev/null 2>&1; then
    die "Samba is already set up here (/etc/samba/smb.conf). Kiboto writes that file itself; install on a fresh Debian."
  fi
  if command -v docker >/dev/null 2>&1 && [ -n "$(docker ps -aq 2>/dev/null | head -1)" ]; then
    die "Docker already has containers here. Kiboto manages Docker itself; install on a fresh Debian."
  fi
  if [ -s /etc/exports ] && grep -qv '^[[:space:]]*\(#\|$\)' /etc/exports 2>/dev/null; then
    die "NFS exports are already set up here (/etc/exports). Install on a fresh Debian."
  fi
}

# the packages of a list that are not installed
missing() {
  for p in "$@"; do
    dpkg -s "$p" 2>/dev/null | grep -q '^Status: .* installed$' || printf '%s ' "$p"
  done
}

packages() {
  say "Installing the tools Kiboto drives (this takes a few minutes; ZFS is built for this kernel)..."
  export DEBIAN_FRONTEND=noninteractive
  # ZFS is in Debian's "contrib" part, as source that is built on this machine
  for f in /etc/apt/sources.list.d/*.sources; do
    [ -f "$f" ] && sed -i 's/^Components: main$/Components: main contrib non-free-firmware/' "$f"
  done
  apt-get update -qq
  # Only what is not there yet is installed: a second run of this script leaves the held
  # packages at the version they have, as the hold promises.
  # ZFS is built against the headers of the kernel that is running, not of the newest one.
  headers="linux-headers-$(uname -r)"
  if ! dpkg -s "$headers" >/dev/null 2>&1; then
    apt-get install -y -qq --no-install-recommends "$headers" >/dev/null 2>&1 \
      || die "Debian no longer offers the files for the kernel this machine is running ($(uname -r)). Update Debian (apt full-upgrade), restart, and run this again."
  fi
  # shellcheck disable=SC2086
  need=$(missing linux-headers-amd64 $TOOLS)
  # shellcheck disable=SC2086
  [ -z "$need" ] || apt-get install -y -qq --no-install-recommends $need >/dev/null
  need=$(missing zfs-dkms zfsutils-linux)
  if [ -n "$need" ]; then
    if grep -rqs 'trixie-backports' /etc/apt/sources.list /etc/apt/sources.list.d; then
      # shellcheck disable=SC2086
      apt-get install -y -qq --no-install-recommends -t trixie-backports $need >/dev/null
    else
      # shellcheck disable=SC2086
      apt-get install -y -qq --no-install-recommends $need >/dev/null
    fi
  fi
  modprobe zfs || die "ZFS was built but does not load on this kernel."
  # shellcheck disable=SC2086
  apt-mark hold $HELD >/dev/null
}

docker_setup() {
  # an address range no home network uses, and logs that cannot fill the system disk
  mkdir -p /etc/docker
  [ -f /etc/docker/daemon.json ] || cat > /etc/docker/daemon.json <<JSON
{
  "bip": "10.212.0.1/24",
  "default-address-pools": [{"base": "10.213.0.0/16", "size": 24}],
  "log-driver": "json-file",
  "log-opts": {"max-size": "10m", "max-file": "3"},
  "live-restore": true
}
JSON
  systemctl enable -q docker
  systemctl restart docker
}

code() {
  src=$1
  [ -d "$src/backend" ] && [ -f "$src/requirements.lock" ] || die "$src does not hold Kiboto's code."
  [ -f "$src/static/index.html" ] || die "$src has no built interface (static/index.html)."
  version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$src/backend/__init__.py" | head -1)
  rel="$PREFIX/releases/${version:-dev}-$(date +%Y%m%d%H%M%S)"
  say "Putting Kiboto ${version:-} in $rel..."
  mkdir -p "$rel"
  for part in backend static app.py requirements.lock packaging build.env; do
    [ -e "$src/$part" ] && cp -a "$src/$part" "$rel/"
  done
  # the Python environment is kept by its requirements, as an update keeps it (native_update.lock_key):
  # versions with the same requirements share one
  key=$( (cat "$rel/requirements.lock"; printf '|py%s' "$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')") | sha256sum | cut -c1-16)
  venv="$PREFIX/venvs/$key"
  if [ ! -f "$venv/.ready" ]; then
    rm -rf "$venv"
    python3 -m venv "$venv"
    "$venv/bin/python" -m pip -q install --no-compile --require-hashes -r "$rel/requirements.lock"
    date > "$venv/.ready"
  fi
  ln -sfn "$venv" "$rel/venv"
  previous=$(readlink "$PREFIX/current" 2>/dev/null || true)
  ln -sfn "$rel" "$PREFIX/current"
  [ -n "$previous" ] && printf '%s\n' "$previous" > "$PREFIX/previous"
  return 0
}

# Kiboto's own files out of a published image. The image is named by its digest, so Docker itself
# checks that what arrives is what was named; nothing of the image runs.
must_be_a_digest() {
  case "$1" in
    *@sha256:*) ;;
    *) die "name the version by its digest (image@sha256:...), so that exactly that version is installed." ;;
  esac
}

code_from_image() {
  image=$1
  say "Fetching Kiboto ($image)..."
  docker pull -q "$image" >/dev/null || die "that version could not be downloaded."
  cid=$(docker create "$image" true) || die "that version could not be opened."
  tmp=$(mktemp -d)
  for part in backend static app.py requirements.lock packaging; do
    if ! docker cp "$cid:/app/$part" "$tmp/" 2>/dev/null; then
      docker rm "$cid" >/dev/null; rm -rf "$tmp"
      die "that image is not a Kiboto version for a machine of its own (it has no $part)."
    fi
  done
  docker inspect "$cid" --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | grep -E '^(BUILD_COMMIT|BUILD_DATE|KIBOTO_IMAGE_VARIANT)=' > "$tmp/build.env" || true
  docker rm "$cid" >/dev/null
  code "$tmp"
  rm -rf "$tmp"
}

service() {
  src=$1
  mkdir -p "$DATA" "$ETC" /mnt/storage
  chmod 700 "$DATA"
  [ -f "$ETC/kiboto.env" ] || printf '# Settings for Kiboto as a service, one NAME=value per line. Kept across updates.\n' > "$ETC/kiboto.env"
  date -u +%Y-%m-%dT%H:%M:%SZ > "$ETC/managed"
  install -m 644 "$src/packaging/kiboto.service" "$src/packaging/kiboto-pools.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable -q kiboto-pools.service kiboto.service
  systemctl restart kiboto.service
}

wait_up() {
  i=0
  until curl -fs -m 3 -o /dev/null http://127.0.0.1:8082/api/health; do
    i=$((i + 1))
    [ "$i" -gt 60 ] && die "Kiboto did not start. Look at: journalctl -u kiboto -n 50"
    sleep 2
  done
  addr=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)
  say ""
  say "Kiboto is running. Open http://${addr:-this-machine}:8082 in a browser."
  if [ -r "$DATA/initial-admin-password" ]; then
    say "The first sign-in is the user  admin  with this code:"
    say ""
    say "    $(cat "$DATA/initial-admin-password")"
    say ""
    say "You then choose your own password. Until then this machine also shows the code on its"
    say "own screen and to whoever signs in to it over SSH."
  fi
}

uninstall() {
  must_be_this_machine
  systemctl disable -q --now kiboto.service kiboto-pools.service 2>/dev/null || true
  rm -f /etc/systemd/system/kiboto.service /etc/systemd/system/kiboto-pools.service
  systemctl daemon-reload
  rm -rf "$PREFIX" "$ETC/managed"
  # shellcheck disable=SC2086
  apt-mark unhold $HELD >/dev/null 2>&1 || true
  if [ "${1:-}" = "--purge" ]; then
    rm -rf "$DATA" "$ETC"
    say "Kiboto and its settings are gone."
  else
    say "Kiboto is gone. Its settings stay in $DATA (remove them with --uninstall --purge)."
  fi
  say "Your storage pools, shared folders and apps were not touched; Docker, Samba and the other packages stay installed."
}

case "${1:-}" in
  --from)
    [ -n "${2:-}" ] || die "say where Kiboto's code is: --from <folder>"
    must_be_this_machine; must_be_fresh
    packages; docker_setup; code "$2"; service "$PREFIX/current"; wait_up ;;
  --image | "")
    image=${2:-$KIBOTO_IMAGE}
    [ -n "$image" ] || { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
    must_be_a_digest "$image"; must_be_this_machine; must_be_fresh
    packages; docker_setup; code_from_image "$image"; service "$PREFIX/current"; wait_up ;;
  --uninstall) uninstall "${2:-}" ;;
  *) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
