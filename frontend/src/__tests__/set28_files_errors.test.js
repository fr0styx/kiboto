import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { loadFailReason, FileManagerWindow } from '../components/file-manager.js';

afterEach(() => vi.restoreAllMocks());

const P = FileManagerWindow.prototype;
const fake = (extra = {}) => ({
  list: document.createElement('div'),
  viewport: document.createElement('div'),
  spacer: document.createElement('div'),
  pathInput: document.createElement('input'),
  searchInput: Object.assign(document.createElement('input'), { value: 'zzz' }),
  loadPath: vi.fn(),
  handleSearchInput: vi.fn(),
  ...extra,
});

describe('Files says what happened (SET-28 Files 2, finding 18)', () => {
  it("the reason: the server's own, else plain words", () => {
    expect(loadFailReason({ status: 403, detail: 'Outside your shared folders' })).toBe('Outside your shared folders');
    expect(loadFailReason({ status: 403 })).toBe("You don't have access to this folder.");
    expect(loadFailReason({ status: 404 })).toBe('It is not there any more.');
    expect(loadFailReason({ status: 500, detail: { message: 'disk error' } })).toBe('disk error');
    expect(loadFailReason({ message: 'Network down' })).toBe('Network down');
    expect(loadFailReason({})).toBe('Failed to load directory');
  });

  it('a folder that fails to open says why in the list, with Try again and Back', async () => {
    const fm = fake({ currentPath: '/mnt/user/Photos', showLoadFailed: vi.fn() });
    vi.spyOn(api, 'get').mockRejectedValue(Object.assign(new Error('x'), { status: 404 }));
    await P.loadPath.call(fm, '/mnt/user/Gone');
    expect(fm.showLoadFailed).toHaveBeenCalledWith('/mnt/user/Gone', 'It is not there any more.');

    P.showLoadFailed.call(fm, '/mnt/user/Gone', 'It is not there any more.');
    expect(fm.list.textContent).toContain("This folder couldn't be opened: It is not there any more.");
    expect(fm.pathInput.value).toBe('/mnt/user/Gone');
    const [again, back] = fm.list.querySelectorAll('button');
    expect(back.textContent).toBe('Back to Photos');
    again.click();
    expect(fm.loadPath).toHaveBeenLastCalledWith('/mnt/user/Gone');
    back.click();
    expect(fm.loadPath).toHaveBeenLastCalledWith('/mnt/user/Photos');
    const same = fake({ currentPath: '/mnt/user/Gone' });
    P.showLoadFailed.call(same, '/mnt/user/Gone', 'r');
    expect(same.list.querySelectorAll('button').length).toBe(1);
  });

  it('a search with no hit says so, even with only the parent row left, and clears', () => {
    const fm = fake({ isSearching: true, lastSearch: 'zzz', fileList: [{ name: '..' }] });
    P.renderViewport.call(fm);
    expect(fm.list.textContent).toContain('Nothing here matches "zzz".');
    expect(fm.list.textContent).not.toContain('This folder is empty');
    fm.list.querySelector('button').click();
    expect(fm.searchInput.value).toBe('');
    expect(fm.handleSearchInput).toHaveBeenCalledWith('');
  });

  it('typing a search remembers what was searched', () => {
    const fm = { rawFileList: [{ name: 'a' }], renderViewport: vi.fn() };
    P.handleSearchInput.call(fm, ' qq ');
    expect(fm.lastSearch).toBe('qq');
    expect(fm.fileList).toEqual([]);
  });
});
