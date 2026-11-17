// Files finding 28: Files follows where this server keeps its files, not Unraid's /mnt/user.
import { describe, it, expect, afterEach } from 'vitest';
import { fmHome } from '../components/file-manager-helpers.js';

afterEach(() => {
  delete /** @type {any} */ (window)._fmHome;
  delete /** @type {any} */ (window)._fmRoots;
});

describe('the home folder of Files', () => {
  it('is the pool the server reported, else the first browse root, else /mnt/user', () => {
    expect(fmHome()).toBe('/mnt/user');
    /** @type {any} */ (window)._fmRoots = ['/srv/kiboto/', '/mnt/remotes'];
    expect(fmHome()).toBe('/srv/kiboto');
    /** @type {any} */ (window)._fmRoots = [{ path: '/data' }];
    expect(fmHome()).toBe('/data');
    /** @type {any} */ (window)._fmHome = '/mnt/storage';
    expect(fmHome()).toBe('/mnt/storage');
  });

  it('opens the Recycle Bin of that pool', async () => {
    const { ZettEventBus } = await import('../event-bus.js');
    await import('../components/file-manager.js');
    const seen = [];
    const off = ZettEventBus.on('window:open', (d) => seen.push(d.path));
    /** @type {any} */ (window)._fmHome = '/mnt/storage';
    /** @type {any} */ (window).openRecycleBin();
    expect(seen.at(-1)).toBe('/mnt/storage/.RecycleBin');
    if (typeof off === 'function') off();
  });
});
