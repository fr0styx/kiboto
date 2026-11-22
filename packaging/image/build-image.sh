#!/bin/sh
# Builds Kiboto's install image from Debian's official netinst image:
#
#   sh packaging/image/build-image.sh <debian-13-netinst.iso> <kiboto image>@sha256:<digest> <out.iso> [extra preseed lines]
#
# The image boots into "Install Kiboto": Debian's own installer with packaging/image/preseed.cfg,
# which asks only for the system disk and the root password. The release's install.sh, stamped with
# the given image digest, goes on the image and runs at the first start. Debian's other menu entries
# stay as they were. KIBOTO_ROOT_KEYS=<file> puts SSH public keys on the image that may sign in as
# root on the installed machine. Needs xorriso.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
iso=$1 image=$2 out=$3 extra=${4:-}
[ -f "$iso" ] || { echo "no such image: $iso" >&2; exit 2; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
sh "$here/../../scripts/stamp_installer.sh" "$image" > "$work/install.sh"
cp "$here/preseed.cfg" "$work/preseed.cfg"
[ -n "$extra" ] && cat "$extra" >> "$work/preseed.cfg"
cp "$here/late.sh" "$work/late.sh"
xorriso -osirrox on -indev "$iso" \
  -extract /boot/grub/grub.cfg "$work/grub.cfg" \
  -extract /isolinux/txt.cfg "$work/txt.cfg" \
  -extract /isolinux/isolinux.cfg "$work/isolinux.cfg" >/dev/null 2>&1
chmod u+w "$work"/*.cfg
args="auto=true priority=high preseed/file=/cdrom/kiboto/preseed.cfg"
# UEFI: Kiboto first, chosen after 10 seconds
{
  printf 'set default=0\nset timeout=10\n'
  printf "menuentry --hotkey=k 'Install Kiboto' {\n    set background_color=black\n"
  printf '    linux    /install.amd/vmlinuz vga=788 %s --- quiet\n' "$args"
  printf '    initrd   /install.amd/gtk/initrd.gz\n}\n'
  cat "$work/grub.cfg"
} > "$work/grub.new"
# BIOS: the same entry, the default after 10 seconds
{
  printf 'label kiboto\n\tmenu label Install ^Kiboto\n\tmenu default\n\tkernel /install.amd/vmlinuz\n'
  printf '\tappend vga=788 initrd=/install.amd/gtk/initrd.gz %s --- quiet\n' "$args"
  cat "$work/txt.cfg"
} > "$work/txt.new"
sed 's/^timeout 0$/timeout 100/' "$work/isolinux.cfg" > "$work/isolinux.new"
keys=""
[ -n "${KIBOTO_ROOT_KEYS:-}" ] && keys="-map $KIBOTO_ROOT_KEYS /kiboto/authorized_keys"
rm -f "$out"
# shellcheck disable=SC2086
xorriso -indev "$iso" -outdev "$out" $keys \
  -map "$work/preseed.cfg" /kiboto/preseed.cfg \
  -map "$work/late.sh" /kiboto/late.sh \
  -map "$work/install.sh" /kiboto/install.sh \
  -map "$work/grub.new" /boot/grub/grub.cfg \
  -map "$work/txt.new" /isolinux/txt.cfg \
  -map "$work/isolinux.new" /isolinux/isolinux.cfg \
  -boot_image any replay >/dev/null 2>&1
echo "$out"
