// A shared folder on a pool that is away says so, instead of looking empty.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { fetchAndRenderNetworkShares } from '../components/chassis-visualizer.js';
import { api } from '../api.js';

const share = (name, extra = {}) => ({
  name,
  comment: '',
  security: 'public',
  export_smb: true,
  mountpoint: `/mnt/storage/tank/${name}`,
  used_bytes: 0,
  free_bytes: 2000,
  total_bytes: 3000,
  used_pct: 0,
  ...extra,
});

describe('a shared folder whose pool is away', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  it('names the pool and says nothing is lost; a folder on a pool that is here shows its space', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/storage/shares')
        return Promise.resolve({
          platform: 'generic_linux',
          is_observer_mode: false,
          shares: [share('films', { pool_away: 'tank' }), share('music')],
        });
      if (url === '/api/storage/platform')
        return Promise.resolve({
          platform: 'generic_linux',
          capabilities: { is_observer_mode: false, can_manage_shares: true },
        });
      return Promise.resolve({});
    });
    await fetchAndRenderNetworkShares(container);
    const away = container.querySelectorAll('.share-away');
    expect(away).toHaveLength(1);
    expect(away[0].textContent).toBe(
      'Its pool tank is not here, so the folder is empty until the pool is back. Nothing in it is lost.'
    );
    expect(away[0].getAttribute('role')).toBe('status');
  });

  it('a folder on the system disk of a machine set up for Kiboto says its files are at risk', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/storage/shares')
        return Promise.resolve({
          platform: 'generic_linux',
          is_observer_mode: false,
          shares: [share('storage', { on_system_disk: true, mountpoint: '/mnt/storage/shares' }), share('music')],
        });
      if (url === '/api/storage/platform')
        return Promise.resolve({
          platform: 'generic_linux',
          capabilities: { is_observer_mode: false, can_manage_shares: true },
        });
      return Promise.resolve({});
    });
    await fetchAndRenderNetworkShares(container);
    const warned = container.querySelectorAll('.share-system-disk');
    expect(warned).toHaveLength(1);
    expect(warned[0].textContent).toContain('This folder is on the system disk.');
    expect(container.querySelectorAll('.share-usage-wrap').length).toBeGreaterThan(0); // its space still shows
  });
});
