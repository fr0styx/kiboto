// Ejecting a pool says so in the reader's language, not the hardware layer's English (17 Nov).
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn((title, msg, onOk) => onOk()),
  showDangerConfirm: vi.fn((title, msg, onOk) => onOk()),
  showPromptToast: vi.fn(),
  hideConfirmToast: vi.fn(),
}));

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { fetchAndRenderStorageTopology } from '../components/chassis-visualizer.js';
import { setLanguage } from '../i18n.js';

const pools = {
  platform: 'generic_linux',
  is_observer_mode: false,
  pools: [
    {
      id: 'ext',
      name: 'ext',
      fs_type: 'zfs',
      status: 'HEALTHY',
      used_bytes: 1,
      total_bytes: 2,
      free_bytes: 1,
      used_pct: 50,
      members: [{ name: 'sda', device: 'sda', role: 'data', size_bytes: 1, status: 'OK' }],
    },
  ],
};

async function render() {
  vi.spyOn(api, 'get').mockImplementation((url) => {
    if (url === '/api/storage/pools') return Promise.resolve(pools);
    if (url === '/api/storage/platform')
      return Promise.resolve({ platform: 'generic_linux', capabilities: { can_export_pools: true } });
    if (url === '/api/storage/pools/discover') return Promise.resolve({ discovered_pools: [] });
    return Promise.reject(new Error(url));
  });
  const container = document.createElement('div');
  document.body.appendChild(container);
  await fetchAndRenderStorageTopology(container);
  return container;
}

describe('Safely eject in words', () => {
  afterEach(async () => {
    await setLanguage('en');
    document.body.innerHTML = '';
    vi.restoreAllMocks();
    showToast.mockClear();
  });

  it('a normal and a forced eject, in German', async () => {
    await setLanguage('de');
    const english = { message: "External storage pool 'ext' safely exported and flushed. Safe to disconnect cable." };
    let container = await render();
    vi.spyOn(api, 'post').mockResolvedValueOnce(english);
    container.querySelector('.btn-pool-export').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalled());
    expect(showToast.mock.calls[0][0]).not.toContain('safely exported');
    expect(showToast.mock.calls[0][1]).toBe('success');

    showToast.mockClear();
    container = await render();
    vi.spyOn(api, 'post')
      .mockRejectedValueOnce(new Error('Pool is busy; retry with force=true'))
      .mockResolvedValueOnce(english);
    container.querySelector('.btn-pool-export').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalled());
    expect(showToast.mock.calls.at(-1)[0]).not.toContain('safely exported');
    expect(showToast.mock.calls.at(-1)[1]).toBe('success');
  });
});
