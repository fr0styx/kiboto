import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { api } from '../api.js';
import { personFilesView, startingView, saveFilesView, visibleEntries } from '../components/fm-view-prefs.js';
import { FileManagerWindow } from '../components/file-manager.js';

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('the File Explorer view follows the person (SET-28 Files 4, Files decision 8)', () => {
  it('reads the account first; on a first sign-in the browser wins once', () => {
    expect(personFilesView({ preferences: { files: { view: 'icon' } } })).toEqual({ view: 'icon' });
    expect(personFilesView({ user: { preferences: {} } })).toBeNull();
    expect(personFilesView(null)).toBeNull();
    expect(startingView({ view: 'icon', sort: 'mtime', sort_dir: 'desc', hidden: true }, { view: 'list' })).toEqual({
      view: 'icon',
      sort: 'mtime',
      sort_dir: 'desc',
      hidden: true,
      seed: false,
    });
    expect(startingView(null, { view: 'compact', sort: 'size', sort_dir: 'asc', hidden: false })).toEqual({
      view: 'compact',
      sort: 'size',
      sort_dir: 'asc',
      hidden: false,
      seed: true,
    });
    expect(startingView(null, { view: 'weird', sort: 'nope' })).toMatchObject({
      view: 'list',
      sort: 'name',
      sort_dir: 'asc',
      hidden: false,
    });
    localStorage.setItem('kiboto_fm_view_mode', 'icon');
    localStorage.setItem('kiboto_fm_hidden', '1');
    expect(startingView(null)).toMatchObject({ view: 'icon', hidden: true, seed: true });
  });

  it('saves in this browser at once and in the account a moment later', () => {
    vi.useFakeTimers();
    const user = { preferences: { look: {} } };
    /** @type {any} */ (globalThis).kibotoUser = user;
    const put = vi.spyOn(api, 'put').mockResolvedValue({});
    saveFilesView({ view: 'compact', sort: 'mtime', sort_dir: 'desc', hidden: true });
    expect(localStorage.getItem('kiboto_fm_view_mode')).toBe('compact');
    expect(localStorage.getItem('kiboto_fm_hidden')).toBe('1');
    expect(user.preferences.files).toEqual({ view: 'compact', sort: 'mtime', sort_dir: 'desc', hidden: true });
    expect(put).not.toHaveBeenCalled();
    vi.advanceTimersByTime(700);
    expect(put).toHaveBeenCalledWith('/api/auth/me/preferences', {
      files: { view: 'compact', sort: 'mtime', sort_dir: 'desc', hidden: true },
    });
    /** @type {any} */ (globalThis).kibotoUser = null;
    expect(saveFilesView({ view: 'list', sort: 'name', sort_dir: 'asc', hidden: false })).toBeNull();
  });

  it('hides names starting with a dot unless asked, and counts them', () => {
    const entries = [{ name: '..' }, { name: '.git' }, { name: 'a.txt' }, { name: '.DS_Store' }];
    expect(visibleEntries(entries, false)).toEqual({ list: [{ name: '..' }, { name: 'a.txt' }], hidden: 2 });
    expect(visibleEntries(entries, true).hidden).toBe(0);
    expect(visibleEntries(null, false)).toEqual({ list: [], hidden: 0 });
  });

  it('the switch shows the hidden files, says how many there were, and is saved', () => {
    /** @type {any} */ (globalThis).kibotoUser = null;
    const P = FileManagerWindow.prototype;
    const note = document.createElement('div');
    const btn = document.createElement('button');
    const fm = Object.assign(Object.create(P), {
      allEntries: [{ name: '.cache', is_dir: true }, { name: 'b.txt' }, { name: 'a.txt' }],
      showHidden: false,
      viewMode: 'list',
      currentSortBy: 'name',
      currentSortDir: 'asc',
      hiddenNote: note,
      btnHidden: btn,
      fileList: [],
      rawFileList: [],
      spacer: null,
      renderViewport: vi.fn(),
    });
    P.applyHidden.call(fm);
    expect(fm.fileList.map((f) => f.name)).toEqual(['b.txt', 'a.txt'].sort());
    expect(note.hidden).toBe(false);
    expect(note.textContent).toContain('1 hidden item');
    /** @type {HTMLElement} */ (note.querySelector('button')).click(); // no listener in this bare object; call directly
    P.toggleHidden.call(fm);
    expect(fm.showHidden).toBe(true);
    expect(btn.getAttribute('aria-pressed')).toBe('true');
    expect(fm.fileList.map((f) => f.name)).toContain('.cache');
    expect(note.hidden).toBe(true);
    expect(localStorage.getItem('kiboto_fm_hidden')).toBe('1');
    expect(P.filesView.call(fm)).toEqual({ view: 'list', sort: 'name', sort_dir: 'asc', hidden: true });
  });
});
