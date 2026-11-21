#!/bin/sh
# Kiboto on a machine of its own: turns a fresh, minimal Debian 13 into a Kiboto-managed host.
#
#   sh install.sh --from <folder with Kiboto's code>      install
#   sh install.sh --uninstall [--purge]                   take Kiboto off again (--purge: its settings too)
#
# Debian keeps doing what it does: boot, drivers, and its own updates through apt, which stays yours
# to use. Kiboto adds its service, the storage and sharing tools it drives, and Docker for apps.
# Three things are held at the version Kiboto was tested with and move only with a Kiboto update:
# the kernel, ZFS and Docker (`apt-mark showhold` lists them; `apt-mark unhold` gives them back).
# Storage pools and what is on them are never touched by this script, in either direction.
set -eu

PREFIX=/opt/kiboto
DATA=/var/lib/kiboto
ETC=/etc/kiboto
HELD="linux-image-amd64 linux-headers-amd64 zfs-dkms zfsutils-linux docker.io"
# what Kiboto drives: disks and SMART, the three kinds of pool, sharing, apps, virtual machines
TOOLS="smartmontools nvme-cli sg3-utils usbutils btrfs-progs e2fsprogs parted gdisk fuse3 gocryptfs mergerfs \
rclone restic samba nfs-kernel-server docker.io docker-cli qemu-system-x86 qemu-utils ovmf swtpm \
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

packages() {
  say "Installing the tools Kiboto drives (this takes a few minutes; ZFS is built for this kernel)..."
  export DEBIAN_FRONTEND=noninteractive
  # ZFS is in Debian's "contrib" part, as source that is built on this machine
  for f in /etc/apt/sources.list.d/*.sources; do
    [ -f "$f" ] && sed -i 's/^Components: main$/Components: main contrib non-free-firmware/' "$f"
  done
  apt-get update -qq
  # shellcheck disable=SC2086
  apt-get install -y -qq --no-install-recommends linux-headers-amd64 $TOOLS >/dev/null
  if grep -rqs 'trixie-backports' /etc/apt/sources.list /etc/apt/sources.list.d; then
    apt-get install -y -qq --no-install-recommends -t trixie-backports zfs-dkms zfsutils-linux >/dev/null
  else
    apt-get install -y -qq --no-install-recommends zfs-dkms zfsutils-linux >/dev/null
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
  for part in backend static app.py requirements.lock; do
    [ -e "$src/$part" ] && cp -a "$src/$part" "$rel/"
  done
  python3 -m venv "$rel/venv"
  "$rel/venv/bin/pip" -q install --upgrade pip
  "$rel/venv/bin/pip" -q install --no-compile --require-hashes -r "$rel/requirements.lock"
  previous=$(readlink "$PREFIX/current" 2>/dev/null || true)
  ln -sfn "$rel" "$PREFIX/current"
  [ -n "$previous" ] && printf '%s\n' "$previous" > "$PREFIX/previous"
  return 0
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
  say "The first sign-in is the user admin with the password in $DATA/initial-admin-password"
  say "(only root can read it); you choose your own at once."
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
    packages; docker_setup; code "$2"; service "$2"; wait_up ;;
  --uninstall) uninstall "${2:-}" ;;
  *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
