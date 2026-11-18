/** Backup 5: a large empty USB disk is offered for backups in one step. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { offersFor, handlePendingUsb, resetUsbOffer } from '../components/usb-offer.js';
import { api } from '../api.js';
import { showConfirmToast } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));
const openProtectGuide = vi.fn(async () => {});
vi.mock('../components/protect-nas.js', () => ({ openProtectGuide: (...a) => openProtectGuide(...a) }));
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('Use this disk for backups? (Backup 5)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetUsbOffer();
  });
  afterEach(() => vi.restoreAllMocks());

  it('offers setup for an empty disk, after the other offers', () => {
    expect(offersFor({ path: '/mnt/disks/new', setup: true })).toEqual(['setup']);
    expect(offersFor({ path: '/mnt/disks/c', media: true, setup: false })).toEqual(['import']);
  });

  it('Set it up opens Protect this NAS with the disk chosen; Dismiss tells the server', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({});
    handlePendingUsb({ path: '/mnt/disks/new', name: 'new', setup: true, ts: 1 });
    const [title, msg, ok, , opts] = showConfirmToast.mock.calls[0];
    expect(title).toBe('Use this disk for backups?');
    expect(msg).toContain('new has no backups yet');
    expect(opts.okText).toBe('Set it up');
    await ok();
    expect(openProtectGuide).toHaveBeenCalledWith('usb|/mnt/disks/new');
    handlePendingUsb({ path: '/mnt/disks/new', name: 'new', setup: true, ts: 2 });
    await showConfirmToast.mock.calls[1][3]();
    expect(post).toHaveBeenCalledWith('/api/usb/dismiss');
    await flush();
  });
});
