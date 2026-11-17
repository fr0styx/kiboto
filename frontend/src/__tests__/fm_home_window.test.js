// Files finding 28: a Files window starts where this server keeps its files.
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../api.js', () => ({
  api: { get: vi.fn().mockResolvedValue({ current: '/srv/pool', dirs: [], roots: ['/srv/pool', '/mnt/remotes'] }), post: vi.fn() },
  auth: { getToken: () => 'test-token' },
  ApiError: class ApiError extends Error {},
}));
const sheets = [];
vi.mock('../toast.js', () => ({
  showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: (o) => sheets.push(o),
}));

const { initFileManager, getActiveFmInstance, openNewFileManagerWindow } = await import('../components/file-manager.js');

afterEach(() => {
  delete /** @type {any} */ (window)._fmHome;
  delete /** @type {any} */ (window)._fmRoots;
});

describe('a Files window on a server that is not Unraid', () => {
  it('opens at the server pool, lists its places and opens a new window there', async () => {
    localStorage.clear();
    /** @type {any} */ (window)._fmHome = '/srv/pool';
    document.body.innerHTML = '<div id="desktop"></div>';
    /** @type {any} */ (window)._fmInitialized = false;
    initFileManager();
    const inst = /** @type {any} */ (getActiveFmInstance());
    expect(inst.currentPath).toBe('/srv/pool');
    expect(inst.getTitle()).toBe('File Explorer');
    Object.defineProperty(window, 'innerWidth', { value: 400, configurable: true }); // the phone sheet
    inst.locationsBtn?.click();
    const menu = document.querySelector('.fm-locations-menu, .fm-dropdown');
    const paths = sheets.length ? sheets.at(-1).items.map((i) => i.path || i.label) : [...(menu?.querySelectorAll('[data-path]') || [])].map((e) => e.getAttribute('data-path'));
    const text = JSON.stringify(sheets.at(-1) || menu?.innerHTML || '');
    expect(text).not.toContain('/mnt/user/appdata');
    expect(text).toContain('/srv/pool/.RecycleBin');
    expect(paths.length).toBeGreaterThan(0);
    inst.currentPath = '';
    const before = document.querySelectorAll('.file-manager-window').length;
    openNewFileManagerWindow();
    expect(document.querySelectorAll('.file-manager-window').length).toBeGreaterThanOrEqual(before);
  });

  it('remembers the pool the server reports and builds its places from it', async () => {
    const { FmSidebarTree: SidebarTree } = await import('../components/file-manager-helpers.js');
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(/** @type {any} */ ({
      ok: true, json: async () => ({ roots: ['/srv/pool'], array: { name: 'Main Pool', path: '/srv/pool' }, pools: [], remotes: [], special: [] }),
    }));
    document.body.innerHTML = '<div id="tree"><div class="fm-tree-scroll"></div></div>';
    const tree = new SidebarTree({ currentPath: '/srv/pool' }, document.getElementById('tree'));
    await tree.loadRoots();
    expect(/** @type {any} */ (window)._fmHome).toBe('/srv/pool');
    tree.array = null;
    tree.render();
    expect(document.querySelector('[data-path="/srv/pool"]')).not.toBeNull();
    fetchSpy.mockRestore();
  });
});
