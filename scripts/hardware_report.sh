#!/bin/sh
# What a machine is made of, as Kiboto on a machine of its own would see it, for the list of
# tested hardware and for a Debian live USB on a box before Kiboto goes on it:
#
#   sh hardware_report.sh > report.txt
#
# Only reads: nothing is mounted, written, installed or sent, and no drive is asked anything
# (no SMART, no spin-up beyond what starting the machine did). Serial numbers and network
# addresses are left out, so the report can be shared. Runs as any user; as root it also sees
# the kernel log.
set -u

section() { printf '\n== %s\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }
show() { [ -e "$1" ] && printf '%s: %s\n' "$1" "$(tr -d '\0' < "$1" 2>/dev/null | head -c 200)"; }

section "System"
uname -srm
[ -r /etc/os-release ] && . /etc/os-release && echo "${PRETTY_NAME:-unknown}"
for f in sys_vendor product_name board_vendor board_name bios_version; do
  show "/sys/class/dmi/id/$f"
done
[ -d /sys/firmware/efi ] && echo "boot: UEFI" || echo "boot: BIOS (legacy)"
ls /sys/class/tpm 2>/dev/null | sed 's/^/TPM: /' || true
[ -e /sys/class/tpm/tpm0 ] || echo "TPM: none seen"

section "Processor and memory"
grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | sed 's/^ //'
echo "cores: $(grep -c ^processor /proc/cpuinfo 2>/dev/null)"
grep -E '^(MemTotal|SwapTotal)' /proc/meminfo 2>/dev/null
grep -qwE 'vmx|svm' /proc/cpuinfo 2>/dev/null && echo "virtualisation: yes" || echo "virtualisation: not offered"
[ -d /sys/kernel/iommu_groups ] && echo "IOMMU groups: $(ls /sys/kernel/iommu_groups 2>/dev/null | wc -l)"

section "PCI devices and their drivers"
if have lspci; then lspci -nnk 2>/dev/null; else
  for d in /sys/bus/pci/devices/*; do
    drv=$(basename "$(readlink "$d/driver" 2>/dev/null)" 2>/dev/null)
    printf '%s %s:%s %s\n' "$(basename "$d")" "$(cat "$d/vendor")" "$(cat "$d/device")" "${drv:-no driver}"
  done
fi

section "USB devices"
if have lsusb; then lsusb 2>/dev/null; else
  for d in /sys/bus/usb/devices/*; do
    [ -r "$d/idVendor" ] && printf '%s:%s %s\n' "$(cat "$d/idVendor")" "$(cat "$d/idProduct")" "$(cat "$d/product" 2>/dev/null)"
  done
fi

section "Drives (no serial numbers)"
if have lsblk; then
  lsblk -d -o NAME,MODEL,SIZE,TRAN,ROTA,TYPE 2>/dev/null | grep -v ' loop\| rom\|^loop\|^sr'
else
  ls /sys/block
fi

section "Network ports (no addresses)"
for n in /sys/class/net/*; do
  name=$(basename "$n"); [ "$name" = lo ] && continue
  [ -e "$n/device" ] || continue  # bridges, veth and the like: not a port of the machine
  drv=$(basename "$(readlink "$n/device/driver" 2>/dev/null)" 2>/dev/null)
  printf '%s driver=%s state=%s speed=%s\n' "$name" "${drv:-none}" "$(cat "$n/operstate" 2>/dev/null)" \
    "$(cat "$n/speed" 2>/dev/null || echo ?)"
done

section "Fans and temperatures (hwmon)"
for h in /sys/class/hwmon/hwmon*; do
  [ -e "$h/name" ] || continue
  printf '%s: %s' "$(basename "$h")" "$(cat "$h/name")"
  fans=$(ls "$h" 2>/dev/null | grep -c '^fan[0-9]*_input$')
  pwms=$(ls "$h" 2>/dev/null | grep -c '^pwm[0-9]*$')
  temps=$(ls "$h" 2>/dev/null | grep -c '^temp[0-9]*_input$')
  printf '  fans=%s pwm=%s temps=%s\n' "$fans" "$pwms" "$temps"
  for f in "$h"/fan*_input; do
    rpm=$(cat "$f" 2>/dev/null) && printf '    %s %s rpm\n' "$(basename "$f")" "$rpm"
  done
done

section "Front screen, light bar and button"
ls -l /dev/fb* 2>/dev/null || echo "no framebuffer"
for c in /sys/class/drm/card*-*; do [ -e "$c/status" ] && printf '%s %s\n' "$(basename "$c")" "$(cat "$c/status")"; done
ls /sys/class/backlight 2>/dev/null | sed 's/^/backlight: /'
ls -l /dev/ttyACM* /dev/ttyUSB* 2>/dev/null || echo "no USB serial ports"
for h in /sys/class/hidraw/hidraw*; do
  [ -e "$h/device/uevent" ] && printf '%s %s\n' "$(basename "$h")" "$(grep -E '^HID_NAME=' "$h/device/uevent" | cut -d= -f2-)"
done
ls /sys/class/leds 2>/dev/null | sed 's/^/led: /'

section "Graphics and AI chip"
for r in /dev/dri/renderD*; do
  [ -e "$r" ] || continue
  drv=$(basename "$(readlink "/sys/class/drm/$(basename "$r")/device/driver" 2>/dev/null)" 2>/dev/null)
  echo "$r driver=${drv:-?}"
done
for a in /sys/class/accel/accel*; do
  [ -e "$a" ] || continue
  drv=$(basename "$(readlink "$a/device/driver" 2>/dev/null)" 2>/dev/null)
  echo "/dev/$(basename "$a") driver=${drv:-?}"
done
[ -e /sys/class/accel ] || echo "no accel devices"

section "Kernel messages: errors, warnings, missing firmware"
if dmesg >/dev/null 2>&1; then
  dmesg --level=err,warn 2>/dev/null | grep -viE 'serial|[0-9a-f]{2}(:[0-9a-f]{2}){5}' | tail -n 60
  dmesg 2>/dev/null | grep -iE 'firmware.*(fail|missing)|direct firmware load' | tail -n 20
else
  echo "(run as root to include the kernel log)"
fi
