// A trial of new address settings is kept by opening the machine at its new address.
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showActionToast: vi.fn(),
  showPromptToast: vi.fn(),
}));
const toast = await import('../toast.js');
const { keepNetworkFromLink } = await import('../components/auth.js');

const KEY = 'k'.repeat(32);
const page = (search, answer) => ({
  location: { search, pathname: '/', hash: '#files' },
  history: { replaceState: vi.fn() },
  fetch: vi.fn(answer),
});

beforeEach(() => vi.clearAllMocks());

describe('the link that keeps new network settings', () => {
  it('does nothing on an ordinary address', async () => {
    const win = page('?lang=de', async () => ({ ok: true, json: async () => ({ kept: true }) }));
    expect(await keepNetworkFromLink(/** @type {any} */ (win))).toBeNull();
    expect(win.fetch).not.toHaveBeenCalled();
    expect(win.history.replaceState).not.toHaveBeenCalled();
  });

  it('keeps the trial, says so and takes the key out of the address bar', async () => {
    const win = page(`?keep-network=${KEY}&lang=de`, async () => ({ ok: true, json: async () => ({ kept: true }) }));
    expect(await keepNetworkFromLink(/** @type {any} */ (win))).toBe(true);
    expect(win.fetch).toHaveBeenCalledWith('/api/network/host/keep', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ canary_id: KEY }),
    });
    expect(win.history.replaceState).toHaveBeenCalledWith(null, '', '/?lang=de#files');
    expect(toast.showToast).toHaveBeenCalledWith('The new network settings are kept.', 'success');
  });

  it('says when the trial was already over, refused, or the machine did not answer', async () => {
    const over = 'These network settings were not kept: the trial was already over.';
    let win = page(`?keep-network=${KEY}`, async () => ({ ok: true, json: async () => ({ kept: false }) }));
    expect(await keepNetworkFromLink(/** @type {any} */ (win))).toBe(false);
    expect(win.history.replaceState).toHaveBeenCalledWith(null, '', '/#files');
    expect(toast.showToast).toHaveBeenLastCalledWith(over, 'error');
    win = page(`?keep-network=${KEY}`, async () => ({ ok: false, json: async () => ({ detail: 'no' }) }));
    expect(await keepNetworkFromLink(/** @type {any} */ (win))).toBe(false);
    win = page(`?keep-network=${KEY}`, async () => {
      throw new Error('offline');
    });
    expect(await keepNetworkFromLink(/** @type {any} */ (win))).toBe(false);
    expect(toast.showToast).toHaveBeenCalledTimes(3);
  });
});
