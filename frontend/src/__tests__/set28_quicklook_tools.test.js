import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
vi.mock('../utils.js', async (orig) => ({ ...(await orig()), copyText: vi.fn(async () => {}) }));

const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { copyText } = await import('../utils.js');
const { copyKind, isArchiveName, triggerCopy, openFilePreviewModal, closeFilePreviewModal } = await import('../components/file-preview-modal.js');

const q = (sel) => /** @type {HTMLElement} */ (document.querySelector(sel));

afterEach(() => {
  closeFilePreviewModal();
  vi.restoreAllMocks();
  vi.mocked(showToast).mockClear();
  vi.mocked(copyText).mockClear();
});

function serve(meta) {
  vi.spyOn(api, 'get').mockImplementation(async (url) => {
    if (url.startsWith('/api/browse')) return { dirs: [] };
    if (url.startsWith('/api/media')) return null;
    return { status: 'ok', size: 2048, ...meta };
  });
}

describe("Quick look's tools match the file type (SET-28 Files 2, finding 23)", () => {
  it('Copy means the text, the picture or the path', () => {
    expect(copyKind({ type: 'text' }, 'notes.csv')).toBe('text');
    expect(copyKind({ type: 'image' }, 'a.jpg')).toBe('image');
    expect(copyKind(null, 'b.heic')).toBe('image');
    expect(copyKind({ type: 'media' }, 'film.mkv')).toBe('path');
    expect(copyKind({ type: 'hex' }, 'backup.zip')).toBe('path');
  });

  it('knows an archive', () => {
    for (const n of ['a.zip', 'b.7z', 'c.tar', 'd.tgz', 'e.TAR.GZ', 'f.rar']) expect(isArchiveName(n)).toBe(true);
    expect(isArchiveName('g.txt')).toBe(false);
    expect(isArchiveName(undefined)).toBe(false);
  });

  it('a CSV offers Copy text and copies the text', async () => {
    serve({ type: 'text', content: 'a,b\n1,2', ext: '.csv', lines_count: 2 });
    await openFilePreviewModal('/mnt/user/t.csv', 't.csv');
    await vi.waitFor(() => expect(q('#quicklook-copy-btn').title).toBe('Copy text'));
    await triggerCopy();
    expect(copyText).toHaveBeenCalledWith('a,b\n1,2');
    expect(showToast).toHaveBeenCalledWith('Text copied.', 'success');
  });

  it('a ZIP says it is an archive, and Copy copies its path without fetching it', async () => {
    serve({ type: 'hex', hex_dump: ['50 4b 03 04'], ext: '.zip' });
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    await openFilePreviewModal('/mnt/user/b.zip', 'b.zip');
    await vi.waitFor(() => expect(q('#quicklook-body').textContent).toContain('A compressed archive'));
    expect(q('#quicklook-body').textContent).not.toContain('50 4b');
    expect(q('#quicklook-copy-btn').getAttribute('aria-label')).toBe('Copy path');
    await triggerCopy();
    expect(copyText).toHaveBeenCalledWith('/mnt/user/b.zip');
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it('other binary files still show their first bytes', async () => {
    serve({ type: 'hex', hex_dump: ['7f 45 4c 46'], ext: '.bin' });
    await openFilePreviewModal('/mnt/user/x.bin', 'x.bin');
    await vi.waitFor(() => expect(q('#quicklook-body').textContent).toContain('7f 45 4c 46'));
  });
});
