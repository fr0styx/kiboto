/** Backup 5: Protect this NAS opens with a just-plugged disk already chosen. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { openProtectGuide, closeGuide } from '../components/protect-nas.js';
import { api } from '../api.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

describe('Protect this NAS with a chosen disk', () => {
  afterEach(() => {
    closeGuide();
    vi.restoreAllMocks();
  });

  it('ticks the disk asked for, and nothing for a disk it does not offer', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url.includes('destinations')
        ? { usb: ['/mnt/disks/new', '/mnt/disks/old'] }
        : url.includes('shares')
          ? { shares: [] }
          : { peers: [] }
    );
    const host = await openProtectGuide('usb|/mnt/disks/new');
    const checked = [...host.querySelectorAll('input[name="target"]')].filter((r) => r.checked).map((r) => r.value);
    expect(checked).toEqual(['usb|/mnt/disks/new']);
    closeGuide(host);
    const again = await openProtectGuide('usb|/mnt/disks/gone');
    expect([...again.querySelectorAll('input[name="target"]')].some((r) => r.checked)).toBe(false);
  });
});
