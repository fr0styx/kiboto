#!/bin/sh
# Installs Kiboto OS for real and checks that it runs:
#
#   sh scripts/os_install_check.sh <kiboto image>@sha256:<digest>
#
# A fresh Debian 13 (Debian's own cloud image, checked against Debian's checksum file) is started as
# a virtual machine with the QEMU of that Kiboto image. packaging/install.sh of this checkout then
# installs that image in it, as it does on a real machine, and the result is looked at: the services,
# the web process and who it runs as, the storage tools, Docker, and the same again after a restart.
# The image is installed with --unsigned, because this runs before a build is signed.
#
# Needs Docker, /dev/kvm, curl, ssh and ssh-keygen. Nothing outside the work folder is touched.
#   KB_OS_DIR     the work folder (default: a new temporary one, removed at the end)
#   KB_OS_BASE    a Debian 13 cloud image already on this machine, instead of downloading one
#   KB_OS_PORT    the port on this machine's loopback for SSH into the virtual machine (default 2230)
#   KB_OS_KEEP=1  leave the virtual machine running at the end, to look at it
#   KB_OS_INSTALLER  another install script than this checkout's (to try the check itself against a broken one)
#   KB_OS_PREPARE=<file>  make a prepared disk instead of checking: a fresh Debian 13 in which ZFS is
#                 built and the installer's other packages are downloaded (not installed: Debian's Samba
#                 would write a config, and the installer then refuses the machine), saved to <file>
#   KB_OS_UPDATE=1  after the restart, also update the machine to the same build through the root
#                 service and go back with Revert, checking it after each (the machine is then a test
#                 machine: it takes main builds and unsigned images, which a real one never does)
#   KB_OS_VM_IMAGE  start the virtual machine with the QEMU of this image instead of the one to install
#                 (CI boots with the last published build while the new one is still being made)
#   KB_OS_IMAGE_CMD with "--wait" in place of the image: a command that prints the image to install.
#                 It runs once the machine is up, so the boot overlaps whatever the command waits for.
#   KB_OS_FROM    an earlier release (image@sha256): it is installed first, a ZFS mirror, a shared folder
#                 and a file are made through Kiboto's API (scripts/os_upgrade_data.py) on two extra
#                 drives, then the machine updates to <image> through the root service and all three
#                 are checked again; this build then makes a new pool with a shared folder on a third
#                 drive, and everything is checked once more after a restart. The update a real
#                 machine takes.
#   KB_OS_PREPARED  such a disk, used instead of a fresh Debian: the install then skips building ZFS,
#                 the slow part. It belongs to one install.sh and one Debian image (the workflow keys
#                 it by both); anything else gets a fresh Debian.
set -eu
IMAGE=${1:-}
usage() { echo "usage: os_install_check.sh <image>@sha256:<digest> | --wait (with KB_OS_IMAGE_CMD and KB_OS_VM_IMAGE)" >&2; exit 2; }
if [ "$IMAGE" = --wait ]; then
  [ -n "${KB_OS_IMAGE_CMD:-}" ] && [ -n "${KB_OS_VM_IMAGE:-}" ] || usage
else
  case "$IMAGE" in *@sha256:*) ;; *) usage ;; esac
fi
# the image whose QEMU and qemu-img run the machine; the one installed in it is $IMAGE
VM_IMAGE=${KB_OS_VM_IMAGE:-$IMAGE}
HERE=$(cd "$(dirname "$0")/.." && pwd)
PORT=${KB_OS_PORT:-2230}
SEED_PORT=$((PORT + 5000))  # where the new machine reads its first-start settings from this one
NAME=kb-os-check-$PORT
DEBIAN=https://cloud.debian.org/images/cloud/trixie/latest
DEBIAN_IMAGE=debian-13-generic-amd64.qcow2
made=""
if [ -n "${KB_OS_DIR:-}" ]; then WORK=$KB_OS_DIR; mkdir -p "$WORK"; else WORK=$(mktemp -d); made=1; fi
KEY=$WORK/id_ed25519
SSH="ssh -i $KEY -p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=8 -o ServerAliveInterval=15 root@127.0.0.1"
failed=0

say() { printf '%s\n' "$*"; }
stage() { printf '\n== %s (%s s)\n' "$*" "$(( $(date +%s) - T0 ))"; }
# a first-sign-in code may be in what the installer prints: it is never shown
hide() { sed 's/[A-Z0-9]\{4\}-[A-Z0-9]\{4\}-[A-Z0-9]\{4\}/(code not shown)/g'; }
end() {
  rc=$?
  if [ "${KB_OS_KEEP:-0}" = 1 ] && [ "$rc" = 0 ]; then
    say "left running: $SSH"
  else
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    [ -n "$made" ] && docker run --rm -v "$WORK":/vm --entrypoint sh "$VM_IMAGE" -c 'rm -rf /vm/* /vm/.[!.]*' >/dev/null 2>&1 && rmdir "$WORK" 2>/dev/null
  fi
  exit "$rc"
}
trap end EXIT
T0=$(date +%s)

[ -e /dev/kvm ] || { say "This machine has no /dev/kvm: a virtual machine cannot be started here."; exit 1; }

stage "A fresh Debian 13"
if [ -n "${KB_OS_PREPARED:-}" ]; then
  BASE=$KB_OS_PREPARED
  [ -f "$BASE" ] || { say "$BASE is not there"; exit 1; }
  say "using the prepared disk $(basename "$BASE"): ZFS is already built in it"
elif [ -n "${KB_OS_BASE:-}" ]; then
  BASE=$KB_OS_BASE
  [ -f "$BASE" ] || { say "$BASE is not there"; exit 1; }
  say "using $BASE"
else
  BASE=$WORK/$DEBIAN_IMAGE
  curl -fsSL --retry 5 --retry-delay 10 -o "$WORK/SHA512SUMS" "$DEBIAN/SHA512SUMS"
  want=$(grep " $DEBIAN_IMAGE\$" "$WORK/SHA512SUMS" | cut -d' ' -f1)
  [ -n "$want" ] || { say "Debian's checksum file does not list $DEBIAN_IMAGE"; exit 1; }
  if [ ! -f "$BASE" ] || [ "$(sha512sum "$BASE" | cut -d' ' -f1)" != "$want" ]; then
    curl -fsSL --retry 5 --retry-delay 10 -o "$BASE" "$DEBIAN/$DEBIAN_IMAGE"
  fi
  [ "$(sha512sum "$BASE" | cut -d' ' -f1)" = "$want" ] || { say "the Debian image does not match Debian's checksum"; exit 1; }
  say "$DEBIAN_IMAGE matches Debian's checksum"
fi

# what the new machine is told at its first start (cloud-init reads it from this machine): root may
# sign in with a key made for this run only
rm -f "$KEY" "$KEY.pub"
ssh-keygen -q -t ed25519 -N "" -C kb-os-check -f "$KEY"
mkdir -p "$WORK/seed"
printf 'instance-id: kb-os-check-%s\nlocal-hostname: kiboto-check\n' "$(date +%s)" > "$WORK/seed/meta-data"
: > "$WORK/seed/vendor-data"
cat > "$WORK/seed/user-data" <<UD
#cloud-config
hostname: kiboto-check
disable_root: false
ssh_pwauth: false
users:
  - name: root
    ssh_authorized_keys:
      - $(cat "$KEY.pub")
growpart: {mode: auto, devices: ['/']}
UD

docker pull -q "$VM_IMAGE" >/dev/null
DATA_DRIVES=""
if [ -n "${KB_OS_FROM:-}" ]; then  # empty 2 GB drives: two for the pool the update must keep, one for a new pool after
  for n in 1 2 3; do
    truncate -s 2G "$WORK/data$n.raw"
    DATA_DRIVES="$DATA_DRIVES -drive file=/vm/data$n.raw,if=none,id=data$n,format=raw -device virtio-blk-pci,drive=data$n,serial=KBUPGRADE$n"
  done
fi
docker rm -f "$NAME" >/dev/null 2>&1 || true
# The machine's own network view: QEMU's forward then listens on this machine's loopback, and the
# guest sees SSH come from its own gateway (through a Docker network it would see that network's
# address, which is the range the Docker inside the guest takes, and its answers would go nowhere).
docker run -d --name "$NAME" --no-healthcheck --network host --device /dev/kvm \
  -v "$WORK":/vm -v "$BASE":/base.qcow2:ro --entrypoint sh "$VM_IMAGE" -c "
    cd /vm/seed && python3 -m http.server $SEED_PORT --bind 127.0.0.1 >/vm/seed.log 2>&1 &
    rm -f /vm/os.qcow2 && qemu-img create -q -f qcow2 -F qcow2 -b /base.qcow2 /vm/os.qcow2 24G
    cp /usr/share/OVMF/OVMF_VARS_4M.fd /vm/vars.fd
    exec qemu-system-x86_64 -enable-kvm -machine q35 -cpu host -smp ${KB_OS_CPUS:-4} -m ${KB_OS_MEM:-4096} -display none \
      -serial file:/vm/console.log \
      -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
      -drive if=pflash,format=raw,file=/vm/vars.fd \
      -drive file=/vm/os.qcow2,if=none,id=os,format=qcow2 -device virtio-blk-pci,drive=os,serial=KBCHECKOS,bootindex=0 \
      -netdev user,id=n0,hostfwd=tcp:127.0.0.1:$PORT-:22 -device virtio-net-pci,netdev=n0,addr=0x9 \
      -smbios 'type=1,serial=ds=nocloud;s=http://10.0.2.2:$SEED_PORT/' -device virtio-rng-pci $DATA_DRIVES" >/dev/null

wait_ssh() {  # wait_ssh <minutes>: until the machine answers
  i=0
  until $SSH true 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -gt $(( $1 * 12 )) ]; then
      say "no SSH after $1 minutes. The machine's screen said last:"
      docker exec "$NAME" tail -c 1500 /vm/console.log 2>/dev/null | tr -d '\033' | tail -12
      docker logs "$NAME" 2>&1 | tail -5
      return 1
    fi
    docker inspect "$NAME" --format '{{.State.Running}}' 2>/dev/null | grep -q true || { say "the virtual machine stopped:"; docker logs "$NAME" 2>&1 | tail -8; return 1; }
    sleep 5
  done
}
wait_ssh 6
say "up: Debian $($SSH 'cat /etc/debian_version; uname -r' | tr '\n' ' ')"

if [ -n "${KB_OS_PREPARE:-}" ]; then
  stage "Preparing a disk: ZFS built and the other packages downloaded, as install.sh would"
  $SSH "cat > /root/install.sh" < "$HERE/packaging/install.sh"
  # install.sh's own variables and functions (TOOLS, missing), without running it
  $SSH "sh -s" <<'PREP'
set -eu
sed '/^case "${1:-}" in$/,$d' /root/install.sh > /root/install-functions.sh
. /root/install-functions.sh
export DEBIAN_FRONTEND=noninteractive
for f in /etc/apt/sources.list.d/*.sources; do
  [ -f "$f" ] && sed -i 's/^Components: main$/Components: main contrib non-free-firmware/' "$f"
done
apt-get update -qq
apt-get install -y -qq --no-install-recommends "linux-headers-$(uname -r)" >/dev/null
# the module first, then the tools, Debian 13's own: as install.sh does
for pkg in zfs-dkms zfsutils-linux; do
  apt-get install -y -qq --no-install-recommends "$pkg" >/dev/null
done
modprobe zfs
# shellcheck disable=SC2086
need=$(missing linux-headers-amd64 $TOOLS)
# shellcheck disable=SC2086
[ -z "$need" ] || apt-get install -y -qq --no-install-recommends --download-only $need >/dev/null
echo "ZFS $(zfs version | head -1); $(ls /var/cache/apt/archives/*.deb | wc -l) packages downloaded"
# the next start is a first start again: a new machine id, and cloud-init reads its settings anew
cloud-init clean --logs >/dev/null 2>&1 || true
truncate -s 0 /etc/machine-id
rm -f /root/install.sh /root/install-functions.sh
sync
PREP
  $SSH "systemctl poweroff" 2>/dev/null || true
  i=0
  while docker inspect "$NAME" --format '{{.State.Running}}' 2>/dev/null | grep -q true; do
    i=$((i + 1)); [ "$i" -gt 60 ] && { say "the machine did not shut down"; exit 1; }; sleep 3
  done
  out_dir=$(cd "$(dirname "$KB_OS_PREPARE")" && pwd); out_name=$(basename "$KB_OS_PREPARE")
  docker run --rm -v "$WORK":/vm -v "$BASE":/base.qcow2:ro -v "$out_dir":/out --entrypoint qemu-img "$VM_IMAGE" \
    convert -c -O qcow2 /vm/os.qcow2 "/out/$out_name"
  chmod 644 "$KB_OS_PREPARE" 2>/dev/null || true
  say "prepared disk: $KB_OS_PREPARE ($(du -h "$KB_OS_PREPARE" | cut -f1))"
  exit 0
fi

wait_for_build() {
  if [ "$IMAGE" = --wait ]; then
    stage "Waiting for the build to install"
    IMAGE=$(sh -c "$KB_OS_IMAGE_CMD") || { say "no build to install"; exit 1; }
    case "$IMAGE" in *@sha256:*) ;; *) say "not an image by digest: $IMAGE"; exit 1 ;; esac
    say "$IMAGE"
  fi
}
FIRST=$IMAGE
if [ -n "${KB_OS_FROM:-}" ]; then
  case "$KB_OS_FROM" in *@sha256:*) ;; *) say "KB_OS_FROM must name an image by digest"; exit 2 ;; esac
  FIRST=$KB_OS_FROM  # the earlier release first; this run's build is the update
else
  wait_for_build
  FIRST=$IMAGE
fi

stage "Kiboto installs itself"
INSTALLER=${KB_OS_INSTALLER:-$HERE/packaging/install.sh}
if [ -n "${KB_OS_FROM:-}" ] && [ -z "${KB_OS_INSTALLER:-}" ]; then
  # an earlier release is installed with its own installer, as a machine of that time was
  docker pull -q "$KB_OS_FROM" >/dev/null
  docker run --rm --entrypoint cat "$KB_OS_FROM" /app/packaging/install.sh > "$WORK/install-from.sh"
  INSTALLER=$WORK/install-from.sh
  say "with the installer of $(docker run --rm --entrypoint python3 "$KB_OS_FROM" -c 'from backend import __version__; print(__version__)' 2>/dev/null || echo 'that release')"
fi
$SSH "cat > /root/install.sh" < "$INSTALLER"
rc=0
$SSH "sh /root/install.sh --image '$FIRST' --unsigned > /root/install.log 2>&1" || rc=$?
$SSH "tail -25 /root/install.log" | hide
if [ "$rc" != 0 ]; then
  say ""
  say "FAILED: the installer ended with $rc"
  $SSH "systemctl --failed --no-legend --plain | head -10; journalctl -u kiboto -u kiboto-door -n 30 --no-pager 2>/dev/null | cut -c1-240" | hide || true
  exit 1
fi

# one check: a name, and a command run in the machine that must succeed
check() {
  what=$1; shift
  if out=$($SSH "$@" 2>&1); then
    say "  ok      $what"
  else
    failed=$((failed + 1))
    say "  FAILED  $what"
    printf '%s\n' "$out" | hide | tail -6 | sed 's/^/            /'
  fi
}
look() {
  check "Kiboto's service is running" "systemctl is-active -q kiboto"
  check "Kiboto's root service is running" "systemctl is-active -q kiboto-door"
  check "Kiboto answers and says it is healthy" "curl -fs -m 10 http://127.0.0.1:8082/api/health | grep -q '\"status\": *\"ok\"'"
  check "the web process runs as its own user, not as root" "test \"\$(ps -o user= -p \$(systemctl show -p MainPID --value kiboto))\" = kiboto"
  check "the root service runs as root" "test \"\$(ps -o user= -p \$(systemctl show -p MainPID --value kiboto-door))\" = root"
  check "the machine is marked as Kiboto's, and the install as finished" "test -f /etc/kiboto/managed && test ! -e /etc/kiboto/install-started"
  check "no service of the machine has failed" "test -z \"\$(systemctl --failed --no-legend --plain)\" || { systemctl --failed --no-legend --plain; false; }"
  check "ZFS is loaded and its tools answer" "modprobe zfs && zpool list >/dev/null && zfs version | head -2"
  check "btrfs, ext4 and the drive tools are there" "for t in mkfs.btrfs mkfs.ext4 smartctl hdparm nft; do command -v \$t >/dev/null || { echo \"missing: \$t\"; exit 1; }; done"
  check "Docker runs" "docker info >/dev/null"
  check "Samba and NFS are installed" "command -v smbd >/dev/null && command -v exportfs >/dev/null"
  check "ZFS and Docker are held at the tested versions" "apt-mark showhold | grep -q zfs && apt-mark showhold | grep -q docker"
  check "the kernel takes Debian's security fixes (it is not held)" "! apt-mark showhold | grep -q linux-image"
  check "Debian's security fixes are set to install by themselves" "grep -q Debian-Security /etc/apt/apt.conf.d/52kiboto-security"
  # in an update run the administrator has signed in, and the install log is the earlier release's
  [ -n "${KB_OS_FROM:-}" ] || check "Kiboto waits for its first sign-in" "curl -fs -m 10 http://127.0.0.1:8082/api/auth/first-run | grep -q '\"waiting\": *true'"
  check "the page itself is served" "curl -fs -m 10 http://127.0.0.1:8082/ | grep -qi '<title'"
  # an earlier release may still build them on the machine; this build must not
  [ -n "${KB_OS_FROM:-}" ] || check "its Python packages came from the image, nothing downloaded" "grep -q 'Python packages: taken from the image' /root/install.log"
}

stage "The installed machine"
look
$SSH "readlink /opt/kiboto/current; /opt/kiboto/current/venv/bin/python --version; df -h / | tail -1" | sed 's/^/  /'

if [ -n "${KB_OS_FROM:-}" ]; then
  stage "A pool, a shared folder and a file on the earlier release"
  $SSH "cat > /root/os_upgrade_data.py" < "$HERE/scripts/os_upgrade_data.py"
  $SSH "python3 /root/os_upgrade_data.py make /dev/disk/by-id/virtio-KBUPGRADE1 /dev/disk/by-id/virtio-KBUPGRADE2" || failed=$((failed + 1))
  wait_for_build
  stage "The update to this build through the root service"
  $SSH "printf 'KIBOTO_ACCEPT_MAIN_BUILDS=1\nUPDATE_SIGNATURES=off\n' >> /etc/kiboto/kiboto.env && systemctl restart kiboto-door kiboto"
  i=0
  until $SSH "curl -fs -m 5 -o /dev/null http://127.0.0.1:8082/api/health" 2>/dev/null; do
    i=$((i + 1)); [ "$i" -gt 36 ] && break; sleep 5
  done
  before=$($SSH "readlink /opt/kiboto/current")
  $SSH "docker pull -q '$IMAGE' >/dev/null" || say "  the build could not be downloaded"
  $SSH "cd /opt/kiboto/current && sudo -u kiboto env DATA_DIR=/var/lib/kiboto ./venv/bin/python -c 'import sys; from backend import door, __version__; door.call(\"update.start\", image=sys.argv[1], version=__version__, timeout=900)' '$IMAGE'" \
    || say "  the root service refused or failed the update"
  sleep 10
  i=0
  until $SSH "curl -fs -m 5 -o /dev/null http://127.0.0.1:8082/api/health" 2>/dev/null; do
    i=$((i + 1)); [ "$i" -gt 36 ] && break; sleep 5
  done
  check "the update switched to a new release folder" "test \"\$(readlink /opt/kiboto/current)\" != '$before'"
  look
  $SSH "python3 /root/os_upgrade_data.py look" || failed=$((failed + 1))
  stage "A new pool and shared folder on this build, without a restart"
  $SSH "python3 /root/os_upgrade_data.py after /dev/disk/by-id/virtio-KBUPGRADE3" || failed=$((failed + 1))
fi

stage "The same after a restart"
$SSH "systemctl reboot" 2>/dev/null || true
sleep 20
wait_ssh 6
i=0
until $SSH "curl -fs -m 5 -o /dev/null http://127.0.0.1:8082/api/health" 2>/dev/null; do
  i=$((i + 1)); [ "$i" -gt 36 ] && break; sleep 5
done
look
if [ -n "${KB_OS_FROM:-}" ]; then
  $SSH "python3 /root/os_upgrade_data.py look" || failed=$((failed + 1))
fi

# until Kiboto answers again after a switch (up to three minutes)
healthy() {
  i=0
  until $SSH "curl -fs -m 5 -o /dev/null http://127.0.0.1:8082/api/health" 2>/dev/null; do
    i=$((i + 1)); [ "$i" -gt 36 ] && return 1; sleep 5
  done
}
# a command of Kiboto's own, as its web process would ask the root service
as_kiboto() {
  $SSH "cd /opt/kiboto/current && sudo -u kiboto env DATA_DIR=/var/lib/kiboto ./venv/bin/python -c '$1' ${2:-}"
}

if [ "${KB_OS_UPDATE:-0}" = 1 ]; then
  stage "An update to the same build through the root service, and Revert"
  $SSH "printf 'KIBOTO_ACCEPT_MAIN_BUILDS=1\nUPDATE_SIGNATURES=off\n' >> /etc/kiboto/kiboto.env && systemctl restart kiboto-door kiboto"
  healthy || say "  Kiboto did not answer after its settings changed"
  before=$($SSH "readlink /opt/kiboto/current")
  $SSH "docker pull -q '$IMAGE' >/dev/null" || say "  the build could not be downloaded again"
  as_kiboto 'import sys; from backend import door, __version__; door.call("update.start", image=sys.argv[1], version=__version__, timeout=900)' "'$IMAGE'" \
    || say "  the root service refused or failed the update"
  sleep 10
  healthy || say "  Kiboto did not answer after the update"
  check "the update switched to a new release folder" "test \"\$(readlink /opt/kiboto/current)\" != '$before'"
  look
  as_kiboto 'from backend import door; from backend.services import native_update as nu; v = nu.versions_to_go_back_to("/var/lib/kiboto"); door.call("update.back", snapshot_id=v[0]["id"], timeout=600)' \
    || say "  the root service refused or failed Revert"
  sleep 10
  healthy || say "  Kiboto did not answer after Revert"
  check "Revert went back to the release folder from before" "test \"\$(readlink /opt/kiboto/current)\" = '$before'"
  look
fi

stage "Result"
if [ "$failed" != 0 ]; then
  say "FAILED: $failed check(s). What the machine logged last:"
  $SSH "journalctl -u kiboto -u kiboto-door -n 40 --no-pager | cut -c1-240" | hide || true
  exit 1
fi
say "Kiboto OS installs and runs from $IMAGE"
