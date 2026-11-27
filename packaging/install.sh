#!/bin/sh
# Kiboto on a machine of its own: turns a fresh, minimal Debian 13 into a Kiboto-managed host.
#
#   sh install.sh                                         install the version this script was released with
#   sh install.sh --image <image>@sha256:<digest>         install that published version (its signature is checked)
#   sh install.sh --image <image>@sha256:<digest> --unsigned   install a build of your own, without that check
#   sh install.sh --from <folder with Kiboto's code>      install from a folder (for development)
#   sh install.sh --uninstall [--purge]                   take Kiboto off again (--purge: its settings too)
#
# Debian keeps doing what it does: boot, drivers, and its own updates through apt, which stays yours
# to use. Kiboto adds its service, the storage and sharing tools it drives, and Docker for apps.
# Debian's security fixes are installed by themselves, the kernel included, and Kiboto never restarts
# the machine for them. ZFS and Docker are held at the version Kiboto was tested with and move only with
# a Kiboto update (`apt-mark showhold` lists them; `apt-mark unhold` gives them back).
# Storage pools and what is on them are never touched by this script, in either direction.
set -eu
# Kiboto runs as its own user and reads what this script puts in place, whatever umask called it
umask 022

# The version this script installs when it is given none: written in when a version is released,
# with its digest, so what is installed is exactly what the release named.
KIBOTO_IMAGE=""
PREFIX=/opt/kiboto
DATA=/var/lib/kiboto
ETC=/etc/kiboto
HELD="zfs-dkms zfsutils-linux docker.io"
# held by versions before 2.0.7, and again with KIBOTO_SECURITY_UPDATES=0: given back on uninstall
KERNEL="linux-image-amd64 linux-headers-amd64"
# what Kiboto drives: disks and SMART, the three kinds of pool, sharing, apps, virtual machines
TOOLS="mokutil smartmontools hdparm nvme-cli sg3-utils usbutils btrfs-progs e2fsprogs parted gdisk fuse3 gocryptfs mergerfs \
rclone restic samba nfs-kernel-server docker.io docker-cli qemu-system-x86 qemu-utils ovmf swtpm \
systemd-timesyncd tgt nftables libtss2-esys-3.0.2-0t64 libtss2-rc0t64 libtss2-mu-4.0.1-0t64 \
python3-venv ca-certificates curl acl unattended-upgrades"

say() { printf '%s\n' "$*"; }
die() { printf 'Kiboto was not installed: %s\n' "$*" >&2; exit 1; }

# Secure Boot: the firmware's own switch (an EFI variable whose last byte is 1 when it is on)
secure_boot_on() {
  v=$(ls "${KIBOTO_EFIVARS:-/sys/firmware/efi/efivars}"/SecureBoot-* 2>/dev/null | head -1)
  [ -n "$v" ] || return 1
  [ "$(od -An -t u1 "$v" 2>/dev/null | awk '{print $NF}')" = 1 ]
}

must_be_this_machine() {
  [ "$(id -u)" = 0 ] || die "run this as root."
  [ -f /etc/os-release ] || die "this is not a Debian system."
  . /etc/os-release
  [ "${ID:-}" = debian ] && [ "${VERSION_ID:-}" = 13 ] || die "this is ${PRETTY_NAME:-not Debian 13}; Kiboto is installed on Debian 13."
  [ "$(dpkg --print-architecture)" = amd64 ] || die "this machine is not a 64-bit PC (amd64)."
  [ ! -e /.dockerenv ] && [ ! -e /run/.containerenv ] || die "this is a container; Kiboto needs the machine itself."
  command -v systemctl >/dev/null || die "systemd is not running here."
  # Secure Boot on: ZFS is built here and signed with this machine's own key (DKMS makes one); the
  # firmware learns that key once, from the person at the screen, at the next start (secure_boot_key)
}

# Secure Boot: ZFS is signed with this machine's DKMS key, which the firmware does not know yet. The
# key is queued (mokutil) under a one-time code; at the next start the firmware's key manager asks
# the person at the screen to enroll it with that code. Until then ZFS cannot load, so pools wait;
# Kiboto itself runs. kiboto-pools.service tidies up once the key is known (services/secure_boot.py).
SB_KEY=/var/lib/dkms/mok.pub
secure_boot_key() {
  [ -f "$SB_KEY" ] || dkms generate_mok >/dev/null 2>&1 || die "Secure Boot is on, and no key could be made to sign ZFS with (dkms generate_mok)."
  if mokutil --test-key "$SB_KEY" 2>/dev/null | grep -q "already enrolled"; then
    die "ZFS was built and signed with this machine's key, which the firmware knows, but it still does not load on this kernel."
  fi
  sb_code=$(od -An -N8 -tu8 /dev/urandom | tr -dc 0-9 | cut -c1-8)
  [ "${#sb_code}" = 8 ] || die "no code could be made for the Secure Boot key."
  ( umask 077; mkdir -p "$ETC" && printf '%s\n' "$sb_code" > "$ETC/secure-boot-code" )
  mokutil --generate-hash="$sb_code" > "$ETC/secure-boot.hash" 2>/dev/null \
    && mokutil --import "$SB_KEY" --hash-file "$ETC/secure-boot.hash" >/dev/null 2>&1 \
    || { rm -f "$ETC/secure-boot.hash" "$ETC/secure-boot-code"; die "Secure Boot is on, and the key ZFS is signed with could not be handed to the firmware (mokutil). Turn Secure Boot off in the firmware settings and run this again."; }
  rm -f "$ETC/secure-boot.hash"
  mkdir -p /etc/issue.d
  cat > /etc/issue.d/kiboto-secure-boot.issue <<ISSUE

  Kiboto: one step left for Secure Boot, at this screen.
  Restart this machine. When a blue screen asks to "Perform MOK management",
  press a key, choose "Enroll MOK", then "Continue", then "Yes", type $sb_code
  and choose "Reboot". Storage pools are ready after that.

ISSUE
  say ""
  say "Secure Boot is on. One step is left, at this machine's own screen:"
  say "  restart it; when a blue screen asks to \"Perform MOK management\", press a key,"
  say "  choose Enroll MOK, Continue, Yes, type $sb_code and choose Reboot."
  say "  The code is also shown on this machine's screen until then. Pools are ready after that."
  say ""
}

# A machine that already serves files or runs containers has settings Kiboto would write over.
must_be_fresh() {
  [ -e "$ETC/managed" ] && return 0   # Kiboto's own earlier install: this run updates it
  # an earlier run of this script stopped part way (no network, an unsigned version): the Samba,
  # Docker and NFS here are what it installed, and the first start of the install image tries again
  [ -e "$ETC/install-started" ] && return 0
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

# Written once the machine passed must_be_fresh, removed when Kiboto runs: a second run after a
# failure is then not taken for a machine someone else set up.
mark_started() { mkdir -p "$ETC"; : > "$ETC/install-started"; }

# the packages of a list that are not installed
missing() {
  for p in "$@"; do
    dpkg -s "$p" 2>/dev/null | grep -q '^Status: .* installed$' || printf '%s ' "$p"
  done
}

# This machine stays on Debian 13: the same file as packaging/kiboto-debian13.pref (a test keeps the
# two alike), which Kiboto then keeps at each start (native_update.keep_debian)
stay_on_debian13() {
  mkdir -p /etc/apt/preferences.d
  cat > /etc/apt/preferences.d/kiboto-debian13.pref <<'PIN'
Explanation: Written by Kiboto. This machine stays on Debian 13 (trixie): Kiboto's Python environment,
Explanation: its root service and its updater are made for Debian 13's Python, and a move to another
Explanation: Debian release would stop all three at once. Debian 13's own packages and updates install
Explanation: as usual; backports and other sources are not touched by this file. To let apt move the
Explanation: machine anyway, set KIBOTO_KEEP_DEBIAN=0 in /etc/kiboto/kiboto.env and restart Kiboto, which
Explanation: then removes this file.
Package: *
Pin: release o=Debian, n=/^trixie(-.*)?$/
Pin-Priority: 500

Explanation: Every other Debian release (Debian 14 and later, testing, unstable) is never installed.
Package: *
Pin: release o=Debian
Pin-Priority: -1
PIN
  chmod 644 /etc/apt/preferences.d/kiboto-debian13.pref
}

packages() {
  say "Installing the tools Kiboto drives (this takes a few minutes; ZFS is built for this kernel)..."
  export DEBIAN_FRONTEND=noninteractive
  # ZFS is in Debian's "contrib" part, as source that is built on this machine
  for f in /etc/apt/sources.list.d/*.sources; do
    [ -f "$f" ] && sed -i 's/^Components: main$/Components: main contrib non-free-firmware/' "$f"
  done
  apt-get update -qq
  # apt-get update reports a server it could not reach as a warning only; without the contrib list
  # ZFS is then "not found" further down, which says nothing about the network
  if [ -n "$(missing zfs-dkms)" ] && ! apt-cache policy zfs-dkms 2>/dev/null | grep -q 'Candidate: [0-9]'; then
    die "Debian's package servers could not be reached, or the contrib part is missing from the package sources (ZFS is in contrib). Check the network, then run this again."
  fi
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
  # The module first, then the tools: neither package needs the other, so in one go dpkg may set up
  # the tools first, and their service tries to load a module that is not built yet (a red FAILED
  # on the screen during the first start).
  # ZFS is Debian 13's own (2.3), not the backport: Kiboto makes pools limited to its features, so a
  # pool opens on any Debian 13 and on every later ZFS.
  for pkg in zfs-dkms zfsutils-linux; do
    need=$(missing "$pkg")
    [ -n "$need" ] || continue
    # unquoted: missing() ends each name with a space, and "zfs-dkms " is no package
    # shellcheck disable=SC2086
    apt-get install -y -qq --no-install-recommends $need >/dev/null
  done
  if ! modprobe zfs 2>/dev/null; then
    secure_boot_on || die "ZFS was built but does not load on this kernel."
    secure_boot_key
  fi
  systemctl reset-failed zfs-load-module.service 2>/dev/null || true
  # Debian starts its own iSCSI service with the package; Kiboto starts tgtd itself, only when turned on
  systemctl disable -q --now tgt.service 2>/dev/null || true
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
    pyv=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
    if [ -d "$src/site-packages" ]; then  # from the image: the packages it was built and checked with
      say "Python packages: taken from the image."
      rm -rf "$venv/lib/python$pyv/site-packages"
      cp -a "$src/site-packages" "$venv/lib/python$pyv/site-packages"
    else
      say "Python packages: downloading them (the image has none for this machine's Python)..."
      "$venv/bin/python" -m pip -q install --no-compile --require-hashes -r "$rel/requirements.lock"
    fi
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
  # the image's own Python packages, when they are for this machine's Python: nothing is downloaded
  site=$(docker inspect "$cid" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^KIBOTO_SITE=//p')
  pyv=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
  case "$site" in
    /opt/kiboto/*/python"$pyv"/site-packages) docker cp "$cid:$site" "$tmp/site-packages" 2>/dev/null || rm -rf "$tmp/site-packages" ;;
  esac
  docker rm "$cid" >/dev/null
  code "$tmp"
  rm -rf "$tmp"
}

# An image this script does not name is checked before anything of it is unpacked, with a cosign
# release pinned here by version and checksum: the check after unpacking runs the image's own code,
# which an image from somewhere else could have changed to say yes.
COSIGN_VERSION=v3.1.4
COSIGN_SHA256_AMD64=424e2c97d0b45fd7a6b608a87f090f35633f4c23ece5f092d48bba11aaf4bbfa
COSIGN_SHA256_ARM64=ade83b7aac62e131cacfe96d958948b2150cc9efec46a570a2649b8e27dedad2
SIGNER='^https://github\.com/fr0styx/(kiboto|zettnas-toolkit)/\.github/workflows/ci\.yml@refs/'
must_be_signed_before_unpacking() {
  image=$1
  [ "${2:-}" = "--unsigned" ] && return 0
  [ -n "$KIBOTO_IMAGE" ] && [ "$image" = "$KIBOTO_IMAGE" ] && return 0  # released with this script
  case "$(dpkg --print-architecture)" in
    amd64) arch=amd64 sum=$COSIGN_SHA256_AMD64 ;;
    arm64) arch=arm64 sum=$COSIGN_SHA256_ARM64 ;;
    *) die "this machine's kind of processor has no cosign to check the signature with; use --unsigned for a build of your own." ;;
  esac
  say "Checking that Kiboto's own build service signed $image..."
  cdir=$(mktemp -d)
  curl -fsSL --proto '=https' --retry 3 -o "$cdir/cosign" \
    "https://github.com/sigstore/cosign/releases/download/$COSIGN_VERSION/cosign-linux-$arch" \
    || { rm -rf "$cdir"; die "cosign, to check the signature with, could not be downloaded. Kiboto was not installed."; }
  if ! printf '%s  %s\n' "$sum" "$cdir/cosign" | sha256sum -c --status; then
    rm -rf "$cdir"
    die "the cosign downloaded is not the one this script names. Kiboto was not installed."
  fi
  chmod 755 "$cdir/cosign"
  # a release only, signed for its version tag; KIBOTO_ACCEPT_MAIN_BUILDS=1 takes a main build too
  ref='tags/v[0-9][^/]*$'
  [ "${KIBOTO_ACCEPT_MAIN_BUILDS:-0}" = "1" ] && ref='(heads/main|tags/v[0-9][^/]*)$'
  if ! "$cdir/cosign" verify "$image" --certificate-identity-regexp "$SIGNER$ref" \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com > /dev/null 2> "$cdir/said"; then
    said=$(grep -m1 -i 'error' "$cdir/said" | cut -c1-300)
    rm -rf "$cdir"
    die "this version is not signed by Kiboto's build service for a release (${said:-no answer}). Kiboto was not installed."
  fi
  rm -rf "$cdir"
  say "  signed by Kiboto's build service"
}

# The version just unpacked must be signed by Kiboto's own CI (checked with its own code, against the
# public Sigstore log). If it is not, it is taken out again and the machine stays as it was.
must_be_signed() {
  image=$1
  [ "${2:-}" = "--unsigned" ] && { say "Not checking the signature of $image, as asked."; return 0; }
  say "Checking that Kiboto's own build service signed this version..."
  # verify_image, not the module run as a program: a release from before that entry would end with 0 unasked
  # a release only, signed for its version tag; KIBOTO_ACCEPT_MAIN_BUILDS=1 takes a main build too
  check='import inspect, sys
from backend.services.image_signature import verify_image as v
main_too = sys.argv[2] == "1"
new = "tags_only" in inspect.signature(v).parameters
r = v(sys.argv[1], tags_only=not main_too) if new else v(sys.argv[1])
ok = r.ok and (main_too or new or "@refs/tags/v" in r.identity)
print(r.reason if ok or not r.ok else "signed for the main branch, not for a release")
sys.exit(0 if ok else 1)'
  if said=$(cd "$PREFIX/current" && ./venv/bin/python -c "$check" "${image#*@}" "${KIBOTO_ACCEPT_MAIN_BUILDS:-0}" 2>&1); then
    say "  $(printf '%s\n' "$said" | tail -1)"
    return 0
  fi
  said=$(printf '%s\n' "$said" | tail -1)  # its last line says why (no pipe above: it would hide the answer)
  rel=$(readlink "$PREFIX/current")
  if [ -s "$PREFIX/previous" ]; then
    ln -sfn "$(cat "$PREFIX/previous")" "$PREFIX/current"
  else
    rm -f "$PREFIX/current"
  fi
  rm -rf "$rel"
  die "this version is not signed by Kiboto's build service ($said). Nothing was changed."
}

service() {
  src=$1
  mkdir -p "$DATA" "$ETC" /mnt/storage /mnt/disks
  chmod 700 "$DATA"
  [ -f "$ETC/kiboto.env" ] || printf '# Settings for Kiboto as a service, one NAME=value per line. Kept across updates.\n' > "$ETC/kiboto.env"
  date -u +%Y-%m-%dT%H:%M:%SZ > "$ETC/managed"
  install -m 644 "$src/packaging/kiboto.service" "$src/packaging/kiboto-pools.service" "$src/packaging/kiboto-door.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable -q kiboto-pools.service kiboto-door.service kiboto.service
  # Kiboto stopped while the door starts: the door's unit hands the data folder to the user
  # kiboto then (web_user default), which it skips while Kiboto runs
  systemctl stop kiboto.service 2>/dev/null || true
  systemctl restart kiboto-door.service
  systemctl start kiboto.service
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

# A Debian set up with Debian's own installer runs its network with ifupdown. Kiboto changes the
# network only through systemd-networkd, so the same settings move there, as a trial: a timer of the
# machine puts ifupdown back after a while unless this script still reaches the router afterwards.
network_to_networkd() {
  systemctl is-active -q networking 2>/dev/null || return 0
  iface=$(ip -4 route show default | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1)
  [ -n "$iface" ] || { say "The network was left with ifupdown: no default route to move."; return 0; }
  # networkd may run without managing anything (it starts when anything asks it): what counts is
  # whether it manages the port the default route goes through
  [ "$(networkctl list --no-legend "$iface" 2>/dev/null | awk '{print $NF}')" = configured ] && return 0
  gw=$(ip -4 route show default dev "$iface" | sed -n 's/^default via \([0-9.]*\).*/\1/p' | head -1)
  say "Moving this machine's network ($iface) to systemd-networkd, so Kiboto can change it..."
  # what ifupdown has, kept before anything changes: installing systemd-resolved replaces resolv.conf
  cp -L /etc/network/interfaces /etc/network/interfaces.kiboto-before
  [ -f /etc/resolv.conf.kiboto-before ] || cp -L /etc/resolv.conf /etc/resolv.conf.kiboto-before 2>/dev/null || true
  apt-get install -y -qq --no-install-recommends systemd-resolved >/dev/null 2>&1 \
    || { say "  systemd-resolved could not be installed; the network stays with ifupdown."; return 0; }
  file="/etc/systemd/network/05-kiboto-$iface.network"
  mkdir -p /etc/systemd/network "$ETC"
  {
    printf '# Written by Kiboto at install: the settings ifupdown had for %s.\n[Match]\nName=%s\n\n[Network]\n' "$iface" "$iface"
    if grep -Eqs "^iface[[:space:]]+$iface[[:space:]]+inet[[:space:]]+dhcp" /etc/network/interfaces /etc/network/interfaces.d/*; then
      printf 'DHCP=yes\n'
    else
      ip -4 -o addr show dev "$iface" scope global | awk '{print "Address=" $4}' | head -1
      [ -n "$gw" ] && printf 'Gateway=%s\n' "$gw"
      sed -n 's/^nameserver[[:space:]]\{1,\}\([0-9.]\{7,15\}\)$/DNS=\1/p' /etc/resolv.conf.kiboto-before /etc/resolv.conf 2>/dev/null | grep -v '=127\.' | sort -u | head -3
    fi
  } > "$file"
  # the port keeps its name in any slot (the same file Kiboto writes, managed.pin_text); Debian's
  # start-up image names the ports first, from its own copy of the .link files
  mac=$(cat "/sys/class/net/$iface/address" 2>/dev/null)
  if [ -e "/sys/class/net/$iface/device" ] && [ -n "$mac" ]; then
    printf '# Written by Kiboto: the network card %s keeps the name %s in any slot, so the\n# settings Kiboto keeps for that port still find it after the card moved.\n[Match]\nPermanentMACAddress=%s\n\n[Link]\nName=%s\n' \
      "$mac" "$iface" "$mac" "$iface" > "/etc/systemd/network/10-kiboto-$iface.link"
    update-initramfs -u >/dev/null 2>&1 || true
  fi
  # a wired port no file names (the card moved to another slot, or was replaced) still gets an
  # address, so the machine can be reached; the same file Kiboto keeps (hardware/net/managed.py)
  cat > /etc/systemd/network/99-kiboto-any-wired.network <<'ANY'
# Written by Kiboto: a wired port that no other file names gets an address by DHCP, so the machine
# can still be reached after its network card moved to another slot or was replaced (the port then
# has a new name, and the file with its settings no longer matches it).
[Match]
Type=ether
Kind=!*

[Link]
RequiredForOnline=no

[Network]
DHCP=yes

[DHCPv4]
RouteMetric=2048
ANY
  cat > "$ETC/network-back.sh" <<BACK
#!/bin/sh
# Written by Kiboto's install script: ifupdown back, as it was before the move.
systemctl disable -q --now systemd-networkd.service systemd-networkd.socket systemd-resolved.service 2>/dev/null
rm -f "$file" "/etc/systemd/network/10-kiboto-$iface.link"
cp /etc/network/interfaces.kiboto-before /etc/network/interfaces
[ -f /etc/resolv.conf.kiboto-before ] && { rm -f /etc/resolv.conf; cp /etc/resolv.conf.kiboto-before /etc/resolv.conf; }
ip addr flush dev "$iface" scope global
systemctl enable -q networking; systemctl restart networking
ifup "$iface"  # an allow-hotplug port (what Debian's installer writes) is not brought up by the restart
BACK
  chmod 700 "$ETC/network-back.sh"
  systemd-run --quiet --collect --unit kiboto-network-back --on-active=90 sh "$ETC/network-back.sh" \
    || { rm -f "$file"; say "  No way back could be set up; the network stays with ifupdown."; return 0; }
  printf 'auto lo\niface lo inet loopback\n' > /etc/network/interfaces
  systemctl disable -q networking
  ip addr flush dev "$iface" scope global
  systemctl enable -q --now systemd-networkd systemd-resolved
  ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
  networkctl reconfigure "$iface" 2>/dev/null || true
  i=0
  until [ -n "$gw" ] && ping -c1 -W2 "$gw" >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -gt 20 ]; then
      say "  The router did not answer on systemd-networkd: going back to ifupdown now."
      systemctl stop kiboto-network-back.timer 2>/dev/null
      sh "$ETC/network-back.sh"
      return 0
    fi
    sleep 2
  done
  systemctl stop kiboto-network-back.timer 2>/dev/null
  say "  Done: Kiboto can now change this machine's address under Network. ifupdown's settings are kept in /etc/network/interfaces.kiboto-before."
}

uninstall() {
  must_be_this_machine
  systemctl disable -q --now kiboto.service kiboto-pools.service kiboto-door.service 2>/dev/null || true
  rm -f /etc/systemd/system/kiboto.service /etc/systemd/system/kiboto-pools.service /etc/systemd/system/kiboto-door.service
  systemctl daemon-reload
  rm -rf "$PREFIX" "$ETC/managed"
  # shellcheck disable=SC2086
  apt-mark unhold $HELD $KERNEL >/dev/null 2>&1 || true
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
    must_be_this_machine; must_be_fresh; mark_started; stay_on_debian13
    packages; docker_setup; code "$2"; service "$PREFIX/current"; wait_up; network_to_networkd
    rm -f "$ETC/install-started" ;;
  --image | "")
    image=${2:-$KIBOTO_IMAGE}
    [ -n "$image" ] || { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
    must_be_a_digest "$image"; must_be_this_machine; must_be_fresh; mark_started; stay_on_debian13
    packages; docker_setup; must_be_signed_before_unpacking "$image" "${3:-}"
    code_from_image "$image"; must_be_signed "$image" "${3:-}"
    service "$PREFIX/current"; wait_up; network_to_networkd
    # Kiboto runs from the files copied out of the image: the image itself (about 1.9 GB) can go
    docker rmi "$image" >/dev/null 2>&1 || true
    rm -f "$ETC/install-started" ;;
  --uninstall) uninstall "${2:-}" ;;
  *) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
