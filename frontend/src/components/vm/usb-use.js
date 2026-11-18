/**
 * VMs report 26: a USB device the NAS itself uses (a USB disk, the boot stick, the UPS cable) is
 * marked in the picker, and adding it to a machine asks first: it stops working for the NAS.
 */
import { t } from '../../i18n.js';
import { showConfirmToast } from '../../toast.js';

/** The note shown after the device's name, or "". */
export function usbUseNote(d) {
  if (d?.nas_use === 'storage') return t('vmd.usb_use_storage', 'used by this NAS: a USB drive');
  if (d?.nas_use === 'ups') return t('vmd.usb_use_ups', 'used by this NAS: the UPS');
  return '';
}

/** Adds at once, or asks first for a device the NAS uses. */
export function confirmUsbUse(item, add) {
  if (!item?.nas_use) {
    add();
    return false;
  }
  const what =
    item.nas_use === 'ups'
      ? t(
          'vmd.usb_q_ups',
          'This is the UPS this NAS watches. Given to the machine, the NAS can no longer shut down safely on a power cut. Add it anyway?'
        )
      : t(
          'vmd.usb_q_storage',
          'This USB drive is used by this NAS (it may be the boot drive). Given to the machine, it disappears from the NAS. Add it anyway?'
        );
  showConfirmToast(what, () => add());
  return true;
}
