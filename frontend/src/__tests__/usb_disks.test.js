// On a machine set up for Kiboto the Backup page lists USB disks: open ones eject, plugged-in ones open.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const calls = [];
let fail = null;
vi.mock('../api.js', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(async (url, body) => {
      calls.push([url, body]);
      if (fail) throw fail;
      return { path: '/mnt/disks/Holiday' };
    }),
  },
}));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showDangerConfirm: vi.fn() }));

const { usbDisksHtml, usbDiskAction } = await import('../components/offsite-backup.js');
const { showToast } = await import('../toast.js');

beforeEach(() => {
  calls.length = 0;
  fail = null;
  vi.mocked(showToast).mockClear();
});

describe('USB disks on a machine set up for Kiboto', () => {
  it('draws nothing where the host opens disks', () => {
    expect(usbDisksHtml(null)).toBe('');
    expect(usbDisksHtml({ opens_disks: false, disks: [], can_open: [] })).toBe('');
  });

  it('lists open disks with Eject and plugged-in ones with Use this disk', () => {
    document.body.innerHTML = usbDisksHtml({
      opens_disks: true,
      disks: [{ name: 'Backup', path: '/mnt/disks/Backup' }],
      can_open: [{ device: '/dev/sda1', label: 'Holiday', fs: 'exfat', size_bytes: 64e9 }],
    });
    expect(document.querySelector('[data-usb-eject]')?.getAttribute('data-usb-eject')).toBe('/mnt/disks/Backup');
    expect(document.querySelector('[data-usb-open]')?.getAttribute('data-usb-open')).toBe('/dev/sda1');
    expect(document.body.textContent).toContain('Eject a disk before you unplug it.');
    document.body.innerHTML = usbDisksHtml({ opens_disks: true, disks: [], can_open: [] });
    expect(document.body.textContent).toContain('No USB disk is plugged in.');
  });

  it('opens and ejects, says how it went and draws again', async () => {
    const redraw = vi.fn(async () => {});
    document.body.innerHTML =
      '<button data-usb-open="/dev/sda1"></button><button data-usb-eject="/mnt/disks/Backup"></button>';
    const [open, eject] = document.querySelectorAll('button');
    await usbDiskAction(open, redraw);
    await usbDiskAction(eject, redraw);
    expect(calls).toEqual([
      ['/api/usb/open', { device: '/dev/sda1' }],
      ['/api/usb/eject', { path: '/mnt/disks/Backup' }],
    ]);
    expect(redraw).toHaveBeenCalledTimes(2);
    expect(showToast).toHaveBeenCalledWith('The disk is open at /mnt/disks/Holiday.', 'success');
    fail = new Error('The disk is still in use');
    await usbDiskAction(eject, redraw);
    expect(eject.hasAttribute('disabled')).toBe(false);
    expect(showToast).toHaveBeenLastCalledWith('The disk is still in use', 'error');
  });
});
