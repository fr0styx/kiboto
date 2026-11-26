#!/bin/sh
# Kiboto OS: run by Debian after a kernel or its headers are installed (as
# /etc/kernel/postinst.d/zzz-kiboto-zfs and /etc/kernel/header_postinst.d/zzz-kiboto-zfs, after
# DKMS and update-grub). Debian's security fixes bring new kernels by themselves, and DKMS builds ZFS
# for each one. A kernel without ZFS would start without the storage pools, so while the newest
# kernel has no ZFS the machine keeps starting the kernel it runs now, and Kiboto's Updates page
# says so. Nothing is restarted, and a kernel install never fails because of this script.
set -u
flag=${KIBOTO_ZFS_FLAG:-/etc/kiboto/kernel-without-zfs}
modules=${KIBOTO_MODULES:-/lib/modules}
grubcfg=${KIBOTO_GRUB_CFG:-/boot/grub/grub.cfg}

has_zfs() {
  for f in "$modules/$1"/updates/dkms/zfs.ko* "$modules/$1"/extra/zfs.ko*; do
    [ -e "$f" ] && return 0
  done
  return 1
}

# a machine without ZFS has nothing to keep
dpkg-query -W -f='${Status}' zfs-dkms 2>/dev/null | grep -q 'ok installed' || exit 0
newest=$(for d in "$modules"/*/kernel; do [ -d "$d" ] && basename "$(dirname "$d")"; done | sort -V | tail -n 1)
[ -n "$newest" ] || exit 0

if has_zfs "$newest"; then
  # ZFS came for the newest kernel (its headers arrived, or a later kernel): it may start again
  if [ -f "$flag" ]; then
    rm -f "$flag"
    grub-set-default 0 >/dev/null 2>&1 || true
  fi
  exit 0
fi

running=$(uname -r)
# the newest is the one running, or the running one has no ZFS either: keeping it gains nothing
[ "$newest" != "$running" ] && has_zfs "$running" || exit 0
mkdir -p "$(dirname "$flag")"
printf '%s\n' "$newest" > "$flag"
# GRUB's saved entry (GRUB_DEFAULT=saved, /etc/default/grub.d/90-kiboto.cfg), by the ids update-grub gave
sub=$(grep -o 'gnulinux-advanced-[0-9a-f-]*' "$grubcfg" 2>/dev/null | head -n 1)
entry=$(grep -oF "gnulinux-$running-advanced-${sub#gnulinux-advanced-}" "$grubcfg" 2>/dev/null | head -n 1)
if [ -n "$sub" ] && [ -n "$entry" ]; then
  grub-set-default "$sub>$entry" >/dev/null 2>&1 || true
fi
echo "Kiboto: ZFS is not built for kernel $newest yet, so this machine keeps starting $running." >&2
exit 0
