/** Backup 5: each folder with the copies outside this NAS that hold it; folders left out on purpose. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { folderLine, foldersHtml, renderFolders } from '../components/backup-folders.js';
import { api } from '../api.js';
import { showToast } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));
const flush = () => new Promise((r) => setTimeout(r, 0));
const FOLDERS = [
  { name: 'photos', copies: [{ name: 'Nightly', last_ok: 1763300000 }], partly: [] },
  { name: 'docs', copies: [], partly: [{ name: 'Cloud' }] },
  { name: 'music', copies: [], partly: [] },
  { name: 'tmp', copies: [], partly: [], left_out: true },
  { name: 'old', copies: [{ name: 'Weekly', last_ok: 0 }], partly: [] },
];

describe('folders and their copies (Backup 5)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div><div id="backup-verdict-mount"></div></div>';
    vi.clearAllMocks();
  });
  afterEach(() => vi.restoreAllMocks());

  it("says each folder's state in words", () => {
    expect(folderLine(FOLDERS[0]).text).toMatch(/^Copied by Nightly, last /);
    expect(folderLine(FOLDERS[1]).text).toBe('Partly copied by Cloud');
    expect(folderLine(FOLDERS[2]).text).toBe('No copy outside this NAS');
    expect(folderLine(FOLDERS[3]).text).toBe('Left out on purpose');
    expect(folderLine(FOLDERS[4]).text).toBe('Copied by Weekly');
  });

  it('opens when a folder has no copy, with a box to leave it out', () => {
    document.body.innerHTML = foldersHtml(FOLDERS, true);
    expect(document.querySelector('details').open).toBe(true);
    expect(document.querySelector('summary').textContent).toContain('1 folder has no copy outside this NAS');
    expect([...document.querySelectorAll('[data-bkf-left]')].map((b) => b.dataset.bkfLeft)).toEqual(['music', 'tmp']);
    document.body.innerHTML = foldersHtml([FOLDERS[0], FOLDERS[3]], false);
    expect(document.querySelector('details').open).toBe(false);
    expect(document.querySelector('summary').textContent).toContain('Every folder has a copy');
    expect(document.querySelector('[data-bkf-left]')).toBeNull();
  });

  it('draws under the verdict and saves a choice', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ folders: FOLDERS });
    const put = vi.spyOn(api, 'put').mockResolvedValueOnce({}).mockRejectedValueOnce(new Error('denied'));
    const mount = document.getElementById('backup-verdict-mount');
    await renderFolders(mount);
    expect(mount.nextElementSibling.id).toBe('backup-folders');
    const box = document.querySelector('[data-bkf-left="music"]');
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    await flush();
    await flush();
    expect(put).toHaveBeenCalledWith('/api/system/protection/folders/left-out', { name: 'music', left_out: true });
    document.querySelector('[data-bkf-left="music"]').dispatchEvent(new Event('change'));
    await flush();
    await flush();
    expect(showToast).toHaveBeenCalledWith('denied', 'error');
    get.mockResolvedValue({ folders: [] });
    await renderFolders(mount);
    expect(document.getElementById('backup-folders')).toBeNull();
    get.mockRejectedValue(new Error('403'));
    await renderFolders(mount);
    await renderFolders(null);
  });
});
