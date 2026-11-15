import { describe, it, expect, vi, beforeEach } from 'vitest';

const get = vi.fn();
vi.mock('../api.js', () => ({ api: { get } }));

const rd = await import('../components/restore-door.js');
const SNAPS = [
  { name: 'photos@auto-1', path: '/mnt/pool/photos', created_at: 1800000000 },
  { name: 'photos@auto-2', path: '/mnt/pool/photos', created_at: 1800086400 },
  { name: 'docs_20260101', path: '/mnt/pool/docs', created_at: 1790000000 },
];

describe('Get something back (SET-21 stage 2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="m"></div><h3 id="offsite-title"></h3>';
  });

  it('groups snapshots by folder, newest first; a whole-folder rollback takes only Kiboto-named ones', () => {
    expect(rd.folderOf(SNAPS[0])).toBe('photos');
    expect(rd.folderOf(SNAPS[2])).toBe('docs');
    const all = rd.groupSnapshots(SNAPS);
    expect(Object.keys(all).sort()).toEqual(['docs', 'photos']);
    expect(all.photos.map((s) => s.name)).toEqual(['photos@auto-2', 'photos@auto-1']);
    expect(Object.keys(rd.groupSnapshots(SNAPS, true))).toEqual(['photos']);
  });

  it('three buttons and the Recycle Bin first', () => {
    const openBin = vi.fn();
    const mount = /** @type {HTMLElement} */ (document.getElementById('m'));
    rd.installRestoreDoor(mount, { openBin });
    expect([...mount.querySelectorAll('.rd-choice')].map((b) => b.getAttribute('data-rd'))).toEqual(['file', 'folder', 'all']);
    /** @type {HTMLElement} */ (mount.querySelector('[data-rd="bin"]')).click();
    expect(openBin).toHaveBeenCalled();
  });

  it('a file: folder, then day, then that day opens with Restore a copy', async () => {
    get.mockResolvedValue({ snapshots: SNAPS });
    const openSnapshotBrowser = vi.fn();
    const rollbackShare = vi.fn();
    const mount = /** @type {HTMLElement} */ (document.getElementById('m'));
    rd.installRestoreDoor(mount, { snapshots: async () => ({ openSnapshotBrowser, rollbackShare }) });
    /** @type {HTMLElement} */ (mount.querySelector('[data-rd="file"]')).click();
    await vi.waitFor(() => expect(mount.querySelector('[data-rd-folder="photos"]')).not.toBeNull());
    expect(mount.querySelector('[data-rd="file"]')?.getAttribute('aria-pressed')).toBe('true');
    /** @type {HTMLElement} */ (mount.querySelector('[data-rd-folder="photos"]')).click();
    expect(mount.querySelectorAll('[data-rd-snap]').length).toBe(2);
    expect(document.activeElement?.getAttribute('data-rd-snap')).toBe('photos@auto-2');
    /** @type {HTMLElement} */ (mount.querySelector('[data-rd-back]')).click();
    expect(mount.querySelector('[data-rd-folder="docs"]')).not.toBeNull();
    /** @type {HTMLElement} */ (mount.querySelector('[data-rd-folder="photos"]')).click();
    /** @type {HTMLElement} */ (mount.querySelector('[data-rd-snap="photos@auto-1"]')).click();
    await vi.waitFor(() => expect(openSnapshotBrowser).toHaveBeenCalledWith('photos@auto-1'));
    expect(rollbackShare).not.toHaveBeenCalled();
  });

  it('a whole folder rolls back; everything opens the restore window', async () => {
    get.mockResolvedValue({ snapshots: SNAPS });
    const rollbackShare = vi.fn();
    const openRestoreBox = vi.fn();
    const mount = /** @type {HTMLElement} */ (document.getElementById('m'));
    rd.installRestoreDoor(mount, { snapshots: async () => ({ rollbackShare, openSnapshotBrowser: vi.fn() }), restoreBox: async () => ({ openRestoreBox }) });
    /** @type {HTMLElement} */ (mount.querySelector('[data-rd="folder"]')).click();
    await vi.waitFor(() => expect(mount.querySelector('[data-rd-folder="photos"]')).not.toBeNull());
    expect(mount.querySelector('[data-rd-folder="docs"]')).toBeNull();
    /** @type {HTMLElement} */ (mount.querySelector('[data-rd-folder="photos"]')).click();
    /** @type {HTMLElement} */ (mount.querySelector('[data-rd-snap="photos@auto-2"]')).click();
    await vi.waitFor(() => expect(rollbackShare).toHaveBeenCalledWith('photos@auto-2'));
    /** @type {HTMLElement} */ (mount.querySelector('[data-rd="all"]')).click();
    await vi.waitFor(() => expect(openRestoreBox).toHaveBeenCalled());
  });

  it('no earlier versions points to the off-site backups', async () => {
    get.mockRejectedValueOnce(new Error('500'));
    const mount = /** @type {HTMLElement} */ (document.getElementById('m'));
    rd.installRestoreDoor(mount);
    /** @type {HTMLElement} */ (mount.querySelector('[data-rd="file"]')).click();
    await vi.waitFor(() => expect(mount.querySelector('[data-rd="offsite"]')).not.toBeNull());
    expect(mount.textContent).toContain('No earlier versions on this Kiboto yet.');
    Element.prototype.scrollIntoView = vi.fn();
    /** @type {HTMLElement} */ (mount.querySelector('[data-rd="offsite"]')).click();
    expect(document.getElementById('offsite-title')?.scrollIntoView).toHaveBeenCalled();
    expect(rd.foldersHtml({}, 'folder')).toContain('further down this page');
    expect(rd.installRestoreDoor(null)).toBeNull();
  });
});
