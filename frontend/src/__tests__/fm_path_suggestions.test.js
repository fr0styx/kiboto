/** Files on any system: the path box suggests the places the server has, not Unraid's on every system. */
import { describe, it, expect, afterEach } from 'vitest';
import { pathSuggestions, fillPathLists } from '../components/file-manager-helpers.js';

describe('path suggestions', () => {
  afterEach(() => {
    delete window._fmHome;
    document.body.innerHTML = '';
  });

  it('on Unraid: the main folder, its bin, the pools, and appdata, system and /boot', () => {
    const got = pathSuggestions({ array: { path: '/mnt/user' }, pools: [{ path: '/mnt/cache' }], special: [] });
    expect(got).toEqual([
      '/mnt/user',
      '/mnt/user/.RecycleBin',
      '/mnt/cache',
      '/mnt/user/appdata',
      '/mnt/user/system',
      '/boot',
    ]);
  });

  it("on Kiboto's own OS: its own pool, and none of Unraid's places", () => {
    const got = pathSuggestions({
      array: { path: '/mnt/storage' },
      pools: [{ path: '/mnt/fast' }],
      special: [{ path: '/mnt/storage/homes' }],
    });
    expect(got).toEqual(['/mnt/storage', '/mnt/storage/.RecycleBin', '/mnt/fast', '/mnt/storage/homes']);
    expect(got.some((p) => p.startsWith('/mnt/user') || p === '/boot')).toBe(false);
  });

  it("before the server answered: the home Files knows, else Unraid's", () => {
    window._fmHome = '/mnt/storage';
    expect(pathSuggestions()[0]).toBe('/mnt/storage');
  });

  it('fills every Files window', () => {
    document.body.innerHTML =
      '<datalist id="fm-path-list" class="fm-path-list"></datalist><datalist id="w2-path-list" class="fm-path-list"></datalist>';
    fillPathLists({ array: { path: '/mnt/storage' } });
    for (const list of document.querySelectorAll('datalist')) {
      expect([...list.options].map((o) => o.value)).toEqual(['/mnt/storage', '/mnt/storage/.RecycleBin']);
    }
  });
});
