import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { FmSidebarTree } from '../components/file-manager-helpers.js';

describe('Files asks nothing before it opens (SET-28, Files 5)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('the sidebar draws at start-up without asking; opening reads the roots and the favourites', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(/** @type {any} */ ({ ok: true, json: async () => ({ roots: [{ path: '/mnt/user', name: 'user' }] }) }));
    const get = vi.spyOn(api, 'get').mockResolvedValue({ favorites: [] });
    document.body.innerHTML = '<div id="tree"></div>';
    const fm = { currentPath: '/mnt/user', windowEl: document.body };
    const tree = new FmSidebarTree(fm, document.getElementById('tree'));
    await Promise.resolve();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(get).not.toHaveBeenCalled();
    await tree.refresh();
    expect(fetchSpy).toHaveBeenCalledWith('/api/fs/roots', expect.anything());
    expect(get.mock.calls.map((c) => c[0])).toContain('/api/fs/favorites');
    tree.destroy?.();
  });

  it('an announcement that Files opened does not open it a second time', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(/** @type {any} */ ({ ok: true, json: async () => ({ roots: [] }) }));
    vi.spyOn(api, 'get').mockResolvedValue({ entries: [], favorites: [] });
    const { ZettEventBus } = await import('../event-bus.js');
    const fmMod = await import('../components/file-manager.js');
    document.body.innerHTML = '<div id="fm-desktop-icon"></div><div id="file-manager-window" style="display:none"><div class="fm-sidebar-tree"></div></div>';
    const heard = vi.fn();
    ZettEventBus.on('window:open', heard);
    fmMod.openFileManager('/mnt/user'); // builds the window and opens it
    const inst = /** @type {any} */ (window).getActiveFmInstance();
    const open = vi.spyOn(inst, 'open');
    /** @type {HTMLElement} */ (document.getElementById('fm-desktop-icon')).click(); // the desktop icon opens it once and says so
    expect(open).toHaveBeenCalledTimes(1);
    expect(heard.mock.calls.some(([d]) => d && d.id === 'file-manager-window' && d.opened === true)).toBe(true); // handlers get (detail, event)
    open.mockClear();
    ZettEventBus.emit('window:open', { id: 'file-manager-window', opened: true }); // as openFileManager announces it
    expect(open).not.toHaveBeenCalled();
    ZettEventBus.emit('window:open', { id: 'file-manager-window' }); // someone else asking for it
    expect(open).toHaveBeenCalledTimes(1);
  });
});
