#!/bin/sh
# Installs Kiboto OS from its install image (the USB image) in a virtual machine and checks it:
#
#   sh scripts/iso_install_check.sh <kiboto image>@sha256:<digest>
#
# The install image is built as a release builds it (scripts/build_release_image.sh: Debian's netinst
# image, checked against Debian's CD signing key), with three answers added for this run only: the
# system disk, yes to writing it, and root's password locked (root signs in with a key made for this
# run). Debian's installer then runs with no questions; the machine starts from its new disk, installs
# Kiboto at its first start as a real one does, and is looked at. The installer's screen goes to the
# serial console here (console=ttyS0), so a failure shows what it said.
#
# Needs Docker, /dev/kvm, ssh, ssh-keygen and openssl; xorriso, gpg and curl too, or Docker builds the image
# in a Debian container. Nothing outside the work folder is touched.
#   KB_ISO_DIR    the work folder (default: a new temporary one, removed at the end)
#   KB_ISO_PORT   the port on this machine's loopback for SSH into the machine (default 2250)
#   KB_ISO_KEEP=1 leave the machine running at the end, to look at it
#   KB_ISO_MAIN=1 the image is a build of the main branch, signed for main and not for a release: the
#                 installed machine is told to take such builds (it is a test machine then)
#   KB_ISO_FROM   a checkout of the release being checked: its install script, its installer answers
#                 and its first-start script go on the image, built with this checkout's tools
set -eu
IMAGE=${1:-}
case "$IMAGE" in *@sha256:*) ;; *) echo "usage: iso_install_check.sh <image>@sha256:<digest>" >&2; exit 2 ;; esac
HERE=$(cd "$(dirname "$0")/.." && pwd)
PORT=${KB_ISO_PORT:-2250}
NAME=kb-iso-check-$PORT
made=""
if [ -n "${KB_ISO_DIR:-}" ]; then WORK=$KB_ISO_DIR; mkdir -p "$WORK"; else WORK=$(mktemp -d); made=1; fi
KEY=$WORK/id_ed25519
SSH="ssh -i $KEY -p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=8 -o ServerAliveInterval=15 root@127.0.0.1"
failed=0

say() { printf '%s\n' "$*"; }
stage() { printf '\n== %s (%s s)\n' "$*" "$(( $(date +%s) - T0 ))"; }
# a first-sign-in code may be in what the machine prints: it is never shown
hide() { sed 's/[A-Z0-9]\{4\}-[A-Z0-9]\{4\}-[A-Z0-9]\{4\}/(code not shown)/g'; }
end() {
  rc=$?
  if [ "${KB_ISO_KEEP:-0}" = 1 ] && [ "$rc" = 0 ]; then
    say "left running: $SSH"
  else
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    [ -n "$made" ] && docker run --rm -v "$WORK":/vm --entrypoint sh "$IMAGE" -c 'rm -rf /vm/* /vm/.[!.]*' >/dev/null 2>&1 && rmdir "$WORK" 2>/dev/null
  fi
  exit "$rc"
}
trap end EXIT
T0=$(date +%s)
[ -e /dev/kvm ] || { say "This machine has no /dev/kvm: a virtual machine cannot be started here."; exit 1; }

stage "The install image, built as a release builds it, with this run's answers"
rm -f "$KEY" "$KEY.pub"
ssh-keygen -q -t ed25519 -N "" -C kb-iso-check -f "$KEY"
# root's password: random, made for this run and never shown (Debian's installer wants one; a key signs in)
crypted=$(head -c 24 /dev/urandom | base64 | openssl passwd -6 -stdin)
cat > "$WORK/answers.cfg" <<ANSWERS
# For this check only: the system disk, yes to writing it, and root's password (random, hashed)
d-i partman-auto/disk string /dev/vda
d-i partman/confirm boolean true
d-i partman/confirm_nooverwrite boolean true
d-i passwd/root-password-crypted password $crypted
ANSWERS
# a build of the main branch (not a release): the installed machine is a test machine that takes those
if [ "${KB_ISO_MAIN:-0}" = 1 ]; then
  printf '%s\n' "d-i preseed/late_command string sh /cdrom/kiboto/late.sh; mkdir -p /target/etc/kiboto; echo KIBOTO_ACCEPT_MAIN_BUILDS=1 >> /target/etc/kiboto/kiboto.env" >> "$WORK/answers.cfg"
fi
build() {
  KIBOTO_ROOT_KEYS="$1/id_ed25519.pub" KIBOTO_EXTRA_PRESEED="$1/answers.cfg" KIBOTO_EXTRA_ARGS="console=ttyS0,115200" \
    sh "$2/scripts/build_release_image.sh" "$IMAGE" "$1/kiboto.iso"
}
# the release's own files on the image, with this checkout's tools to build and answer it
SRC=$HERE
if [ -n "${KB_ISO_FROM:-}" ]; then
  SRC=$WORK/src
  rm -rf "$SRC" && mkdir -p "$SRC/packaging/image"
  cp -r "$HERE/scripts" "$SRC/"
  cp "$HERE/packaging/image/build-image.sh" "$SRC/packaging/image/"
  cp "$KB_ISO_FROM/packaging/install.sh" "$SRC/packaging/"
  for f in preseed.cfg late.sh NOTICE.txt; do cp "$KB_ISO_FROM/packaging/image/$f" "$SRC/packaging/image/"; done
  say "  the install script and the installer's files of $KB_ISO_FROM"
fi
if command -v xorriso >/dev/null && command -v gpg >/dev/null; then
  build "$WORK" "$SRC" | tail -1
else
  docker run --rm -v "$SRC":/src:ro -v "$WORK":/work -e IMAGE="$IMAGE" debian:13 sh -c "
    apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends xorriso gnupg curl ca-certificates dirmngr >/dev/null
    KIBOTO_ROOT_KEYS=/work/id_ed25519.pub KIBOTO_EXTRA_PRESEED=/work/answers.cfg KIBOTO_EXTRA_ARGS='console=ttyS0,115200' \
      sh /src/scripts/build_release_image.sh \"\$IMAGE\" /work/kiboto.iso" | tail -1
fi
[ -s "$WORK/kiboto.iso" ] || { say "FAILED: the install image was not built"; exit 1; }

docker pull -q "$IMAGE" >/dev/null
vm() {  # vm <qemu args...>: the machine, with the QEMU of the Kiboto image
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run -d --name "$NAME" --no-healthcheck --network host --device /dev/kvm -v "$WORK":/vm --entrypoint sh "$IMAGE" -c "
    exec qemu-system-x86_64 -enable-kvm -machine q35 -cpu host -smp 4 -m 4096 -display none \
      -drive file=/vm/disk.qcow2,if=virtio,format=qcow2 $*" >/dev/null
}

stage "Debian's installer, with no questions"
docker run --rm -v "$WORK":/vm --entrypoint qemu-img "$IMAGE" create -q -f qcow2 /vm/disk.qcow2 24G
vm "-serial file:/vm/install.log -no-reboot -cdrom /vm/kiboto.iso -boot d -netdev user,id=n0 -device virtio-net-pci,netdev=n0"
i=0
while docker inspect "$NAME" --format '{{.State.Running}}' 2>/dev/null | grep -q true; do
  i=$((i + 1))
  if [ "$i" -gt 720 ]; then  # an hour
    say "FAILED: the installer did not finish in an hour. Its screen said last:"
    tail -c 3000 "$WORK/install.log" | tr -d '\033' | tail -25
    exit 1
  fi
  sleep 5
done
grep -q "Installation complete\|Requesting system reboot\|reboot: Restarting system" "$WORK/install.log" \
  || { say "FAILED: the installer stopped before it finished. Its screen said last:"; tail -c 3000 "$WORK/install.log" | tr -d '\033' | tail -25; exit 1; }
say "  installed in $(( $(date +%s) - T0 )) s"

stage "The machine starts from its disk and installs Kiboto"
vm "-serial file:/vm/console.log -netdev user,id=n0,hostfwd=tcp:127.0.0.1:$PORT-:22 -device virtio-net-pci,netdev=n0"
i=0
until $SSH true 2>/dev/null; do
  i=$((i + 1))
  [ "$i" -gt 72 ] && { say "FAILED: no SSH after 6 minutes. The screen said last:"; tail -c 2000 "$WORK/console.log" | tr -d '\033' | tail -15; exit 1; }
  sleep 5
done
# Kiboto installs itself at the first start (late.sh's kiboto-firstboot): it builds ZFS, so it takes a while
i=0
until $SSH "curl -fs -m 5 http://127.0.0.1:8082/api/health" 2>/dev/null | grep -q '"status": *"ok"'; do
  i=$((i + 1))
  if [ "$i" -gt 480 ]; then  # forty minutes
    say "FAILED: Kiboto did not answer within forty minutes of the first start. What the machine logged:"
    $SSH "journalctl -u kiboto-firstboot -u kiboto -u kiboto-door -n 40 --no-pager | cut -c1-220; tail -20 /var/log/kiboto-install.log 2>/dev/null" | hide || true
    exit 1
  fi
  sleep 5
done

check() {
  what=$1; shift
  if out=$($SSH "$@" 2>&1); then say "  ok      $what"; else
    failed=$((failed + 1)); say "  FAILED  $what"; printf '%s\n' "$out" | hide | tail -6 | sed 's/^/            /'
  fi
}
stage "The machine installed from the image"
check "Kiboto's service and its root service are running" "systemctl is-active -q kiboto kiboto-door"
check "Kiboto answers and says it is healthy" "curl -fs -m 10 http://127.0.0.1:8082/api/health | grep -q '\"status\": *\"ok\"'"
check "the web process runs as its own user, not as root" "test \"\$(ps -o user= -p \$(systemctl show -p MainPID --value kiboto))\" = kiboto"
check "the machine is marked as installed from the image" "test -f /etc/kiboto/managed && test -f /etc/kiboto/from-install-image"
check "the firewall is on, with Kiboto's rules" "nft list table inet kiboto >/dev/null"
check "SSH takes the root password until the first sign-in to Kiboto" "test -f /etc/ssh/sshd_config.d/kiboto.conf"
check "Debian's security fixes are set to install by themselves" "grep -q Debian-Security /etc/apt/apt.conf.d/52kiboto-security"
check "ZFS is loaded and its tools answer" "modprobe zfs && zpool list >/dev/null"
check "no service of the machine has failed" "test -z \"\$(systemctl --failed --no-legend --plain)\" || { systemctl --failed --no-legend --plain; false; }"
check "Kiboto waits for its first sign-in" "curl -fs -m 10 http://127.0.0.1:8082/api/auth/first-run | grep -q '\"waiting\": *true'"

stage "Result"
if [ "$failed" != 0 ]; then
  say "FAILED: $failed check(s). What the machine logged last:"
  $SSH "journalctl -u kiboto -u kiboto-door -n 30 --no-pager | cut -c1-220" | hide || true
  exit 1
fi
say "Kiboto OS installs from its install image and runs ($IMAGE)"
