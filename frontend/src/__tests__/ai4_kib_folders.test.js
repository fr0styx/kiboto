/** AI 4: "Kib can read these folders": tick boxes, states in words, a menu with words, "Never read". */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { folderName, folderState, folderRows, kibFoldersHtml, renderKibFolders } from '../components/management/kib-folders.js';
import { kibFolderActions } from '../components/management/ai.js';
import { api } from '../api.js';
import { showToast } from '../toast.js';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

const res = {
  watched_paths: ['/mnt/user/docs', '/mnt/user/extra'],
  excluded_paths: ['/mnt/user/private'],
  available_folders: [{ path: '/mnt/user/docs' }, { path: '/mnt/user/photos', in_standby: true }],
  sync_progress: { state: 'idle' },
  standby_guard: { deferred_queue: [] },
};

describe('Kib folder list (AI 4)', () => {
  beforeEach(() => { document.body.innerHTML = '<div id="kib-folders-mount"></div>'; vi.clearAllMocks(); });
  afterEach(() => vi.restoreAllMocks());

  it('calls a folder by its name', () => {
    expect(folderName('/mnt/user/Family Photos/')).toBe('Family Photos');
    expect(folderName('/')).toBe('/');
    expect(folderName('')).toBe('');
  });

  it('says what Kib is doing with each chosen folder', () => {
    expect(folderState('/mnt/user/docs', res).text).toBe('Up to date');
    expect(folderState('/mnt/user/docs', { sync_progress: { state: 'running', current_path: '/mnt/user/docs/2025/a.pdf' } }).text).toBe('Reading');
    expect(folderState('/mnt/user/docs', { sync_progress: { state: 'running', target_paths: ['/mnt/user/docs'] } }).key).toBe('reading');
    expect(folderState('/mnt/user/docs', { sync_progress: { state: 'running', current_path: '/mnt/user/docsx' } }).key).toBe('ok');
    expect(folderState('/mnt/user/docs', { standby_guard: { deferred_queue: [{ path: '/mnt/user/docs' }] } }).text).toBe('Waiting for a drive to wake');
    expect(folderState('/mnt/user/docs', { standby_guard: { deferred_queue: ['/mnt/user/docs/x'] } }).key).toBe('asleep');
    expect(folderState('/mnt/user/photos', {}, { in_standby: true }).key).toBe('asleep');
    expect(folderState('/x', undefined).key).toBe('ok');
  });

  it('lists found folders and chosen ones, ticked or not', () => {
    expect(folderRows(res).map((r) => [r.path, r.chosen])).toEqual([['/mnt/user/docs', true], ['/mnt/user/photos', false], ['/mnt/user/extra', true]]);
    expect(folderRows({})).toEqual([]);
  });

  it('draws real tick boxes, words and no device names', () => {
    const html = kibFoldersHtml(res);
    document.body.innerHTML = html;
    const boxes = [...document.querySelectorAll('input[type="checkbox"]')];
    expect(boxes.map((b) => b.checked)).toEqual([true, false, true]);
    expect(document.querySelector('label[for="kibf-0"]').textContent).toContain('docs');
    expect(document.body.textContent).toContain('Never read');
    expect(document.body.textContent).toContain('Stop reading and forget this folder (your files stay)');
    expect(html).not.toMatch(/sd[a-z]|RAG|Standby/);
    expect(document.querySelectorAll('details.kibf-menu')).toHaveLength(2); // only chosen folders have a menu
    document.body.innerHTML = kibFoldersHtml({});
    expect(document.body.textContent).toContain('No folders found yet. Add one below.');
    expect(document.body.textContent).not.toContain('Never read');
  });

  it('wires ticks and menu items to the page', () => {
    const acts = { tick: vi.fn(), read: vi.fn(), stop: vi.fn(), forget: vi.fn(), unforget: vi.fn(), add: vi.fn() };
    const mount = document.getElementById('kib-folders-mount');
    renderKibFolders(mount, res, acts);
    const photos = mount.querySelector('input[data-path="/mnt/user/photos"]');
    photos.checked = true;
    photos.dispatchEvent(new Event('change'));
    expect(acts.tick).toHaveBeenCalledWith('/mnt/user/photos', true);
    const menu = mount.querySelector('details');
    menu.setAttribute('open', '');
    menu.querySelector('[data-kibf-act="read"]').click();
    expect(acts.read).toHaveBeenCalledWith('/mnt/user/docs');
    expect(menu.hasAttribute('open')).toBe(false);
    mount.querySelector('[data-kibf-act="stop"]').click();
    mount.querySelector('[data-kibf-act="forget"]').click();
    mount.querySelector('[data-kibf-act="unforget"]').click();
    mount.querySelector('[data-kibf-act="add"]').click();
    expect(acts.stop).toHaveBeenCalledWith('/mnt/user/docs');
    expect(acts.forget).toHaveBeenCalledWith('/mnt/user/docs');
    expect(acts.unforget).toHaveBeenCalledWith('/mnt/user/private');
    expect(acts.add).toHaveBeenCalled();
    renderKibFolders(mount, res, {}); // without actions nothing is wired
    mount.querySelector('[data-kibf-act="add"]').click();
    renderKibFolders(null, res, acts);
  });

  it('the page\'s folder actions call the right routes', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok', watched_paths: [] });
    vi.spyOn(api, 'get').mockResolvedValue({});
    const a = kibFolderActions();
    await a.tick('/mnt/user/photos', true);
    expect(post).toHaveBeenCalledWith('/api/media/folders', { action: 'add', path: '/mnt/user/photos' });
    await a.tick('/mnt/user/photos', false);
    await a.stop('/mnt/user/docs');
    expect(post.mock.calls.filter((c) => c[1]?.action === 'remove').length).toBeGreaterThanOrEqual(2);
    await a.read('/mnt/user/docs');
    await a.forget('/mnt/user/docs');
    await a.unforget('/mnt/user/private');
    expect(post).toHaveBeenCalledWith('/api/ai/folders', { action: 'remove', target: 'excluded', path: '/mnt/user/private' });
    post.mockRejectedValueOnce(new Error('denied'));
    await a.unforget('/mnt/user/private');
    expect(showToast).toHaveBeenLastCalledWith('Could not take the folder off the list: denied', 'error');
    window.openFolderBrowser = vi.fn((start, cb) => cb('/mnt/user/new/'));
    a.add();
    expect(window.openFolderBrowser).toHaveBeenCalledWith('/mnt/user/', expect.any(Function));
    window.openFolderBrowser = vi.fn((start, cb) => cb(''));
    a.add();
    delete window.openFolderBrowser;
    a.add();
  });
});
