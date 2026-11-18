/** VMs report 26: USB devices the NAS uses are marked, and adding one asks first. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import * as toast from '../toast.js';
import { usbUseNote, confirmUsbUse } from '../components/vm/usb-use.js';

describe('USB devices the NAS uses (VMs report 26)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('names what the NAS uses the device for', () => {
    expect(usbUseNote({ nas_use: 'storage' })).toBe('used by this NAS: a USB drive');
    expect(usbUseNote({ nas_use: 'ups' })).toBe('used by this NAS: the UPS');
    expect(usbUseNote({ nas_use: '' })).toBe('');
    expect(usbUseNote(null)).toBe('');
  });

  it('adds a free device at once and asks first for one the NAS uses', () => {
    const ask = vi.spyOn(toast, 'showConfirmToast').mockImplementation((msg, ok) => {
      ok();
    });
    const add = vi.fn();
    expect(confirmUsbUse({ nas_use: '' }, add)).toBe(false);
    expect(add).toHaveBeenCalledTimes(1);
    expect(confirmUsbUse({ nas_use: 'ups' }, add)).toBe(true);
    expect(ask.mock.calls[0][0]).toContain('shut down safely on a power cut');
    expect(confirmUsbUse({ nas_use: 'storage' }, add)).toBe(true);
    expect(ask.mock.calls[1][0]).toContain('it may be the boot drive');
    expect(add).toHaveBeenCalledTimes(3);
  });
});
