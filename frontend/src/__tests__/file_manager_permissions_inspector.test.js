import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { FmInspector, isGuardedSystemDir } from '../components/file-manager-helpers.js';
import { api } from '../api.js';

vi.mock('../api.js', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn().mockResolvedValue({ status: 'ok', path: '/mnt/user/test.txt' }),
  },
  auth: {
    getToken: vi.fn().mockReturnValue('mock-token'),
  },
}));

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
}));

describe('Item 3.4: File Explorer Share Links & POSIX Permissions Inspector', () => {
  let containerEl;
  let mockFm;

  beforeEach(() => {
    vi.clearAllMocks();
    containerEl = document.createElement('div');
    containerEl.className = 'fm-inspector-pane';
    containerEl.innerHTML = `
      <div class="fm-inspector-header">
        <button class="fm-inspector-close-btn">✕</button>
      </div>
      <div class="fm-inspector-content"></div>
    `;
    document.body.appendChild(containerEl);

    mockFm = {
      selectedPaths: new Set(['/mnt/user/documents/report.pdf']),
      fileList: [
        {
          name: 'report.pdf',
          path: '/mnt/user/documents/report.pdf',
          size: 2048,
          is_dir: false,
          mode: '0644',
          mtime: 1700000000,
        },
      ],
      currentPath: '/mnt/user/documents',
    };
  });

  afterEach(() => {
    containerEl.remove();
    document.body.innerHTML = '';
  });

  it('isGuardedSystemDir correctly identifies system and appdata protected paths', () => {
    expect(isGuardedSystemDir('/boot/config/plugins')).toBe(true);
    expect(isGuardedSystemDir('/appdata/db/data')).toBe(true);
    expect(isGuardedSystemDir('/mnt/user/appdata/nextcloud')).toBe(true);
    expect(isGuardedSystemDir('/etc/passwd')).toBe(true);
    expect(isGuardedSystemDir('/sys/devices')).toBe(true);
    expect(isGuardedSystemDir('/mnt/user/documents/file.txt')).toBe(false);
    expect(isGuardedSystemDir('/mnt/user/media/movies')).toBe(false);
  });

  it('renders Permissions tab in inspector and synchronizes octal with checkboxes', async () => {
    const inspector = new FmInspector(mockFm, containerEl);
    inspector.toggle(true);

    // Switch to permissions tab
    inspector.activeTab = 'permissions';
    await inspector.update();

    const octInput = containerEl.querySelector('#fm-insp-octal-input');
    expect(octInput).not.toBeNull();

    const chkUR = containerEl.querySelector('#fm-perm-ur');
    const chkUW = containerEl.querySelector('#fm-perm-uw');
    const chkUX = containerEl.querySelector('#fm-perm-ux');
    expect(chkUR).not.toBeNull();
    expect(chkUW).not.toBeNull();
    expect(chkUX).not.toBeNull();

    // Mode 0755
    octInput.value = '0755';
    octInput.dispatchEvent(new Event('input'));

    expect(chkUR.checked).toBe(true);
    expect(chkUW.checked).toBe(true);
    expect(chkUX.checked).toBe(true);

    const humanMode = containerEl.querySelector('#fm-insp-human-mode');
    expect(humanMode.textContent).toContain('rwxr-xr-x');

    // Toggle off write permission
    chkUW.checked = false;
    chkUW.dispatchEvent(new Event('change'));

    // Should become 0555
    expect(octInput.value).toBe('0555');
  });

  it('calls api.put to update POSIX permissions on user confirmation', async () => {
    const inspector = new FmInspector(mockFm, containerEl);
    inspector.toggle(true);
    inspector.activeTab = 'permissions';
    await inspector.update();

    const octInput = containerEl.querySelector('#fm-insp-octal-input');
    octInput.value = '0640';

    const ownerInput = containerEl.querySelector('#fm-insp-owner-input');
    ownerInput.value = 'appuser';

    const applyBtn = containerEl.querySelector('#fm-insp-apply-perms-btn');
    expect(applyBtn).not.toBeNull();
    await applyBtn.click();

    expect(api.put).toHaveBeenCalledWith(
      '/api/fs/permissions',
      expect.objectContaining({
        path: '/mnt/user/documents/report.pdf',
        mode_octal: '0640',
        owner: 'appuser',
      })
    );
  });

  it('disables permission modifications on guarded paths such as /appdata', async () => {
    mockFm.selectedPaths = new Set(['/mnt/user/appdata/mysql/my.cnf']);
    mockFm.fileList = [
      {
        name: 'my.cnf',
        path: '/mnt/user/appdata/mysql/my.cnf',
        size: 512,
        is_dir: false,
        mode: '0644',
      },
    ];

    const inspector = new FmInspector(mockFm, containerEl);
    inspector.toggle(true);
    inspector.activeTab = 'permissions';
    await inspector.update();

    const banner = containerEl.querySelector('.fm-perm-guarded-banner');
    expect(banner).not.toBeNull();
    expect(banner.textContent).toContain('A system folder');

    const applyBtn = containerEl.querySelector('#fm-insp-apply-perms-btn');
    expect(applyBtn.disabled).toBe(true);
  });
  describe("a folder: what is still the system's goes to the folder's people", () => {
    async function open(path, isDir = true) {
      mockFm.selectedPaths = new Set([path]);
      mockFm.fileList = [{ name: path.split('/').pop(), path, size: 0, is_dir: isDir, mode: '0755' }];
      const inspector = new FmInspector(mockFm, containerEl);
      inspector.toggle(true);
      inspector.activeTab = 'permissions';
      await inspector.update();
      return containerEl.querySelector('#fm-insp-give-btn');
    }

    it("hands what is still the system's to the folder's people and says how many", async () => {
      const { showToast } = await import('../toast.js');
      api.post.mockResolvedValueOnce({ status: 'ok', seen: 12, given: 3 });
      const btn = await open('/mnt/user/documents/Holiday');
      expect(btn).not.toBeNull();
      expect(containerEl.querySelector('#fm-insp-give-box').textContent).toContain('still belong to the system');
      btn.click();
      await vi.waitFor(() => expect(showToast).toHaveBeenCalled());
      expect(api.post).toHaveBeenCalledWith('/api/fs/permissions/like-folder', { path: '/mnt/user/documents/Holiday' });
      expect(showToast.mock.calls[0][0]).toContain("3 items now belong to this folder's people");
      expect(showToast.mock.calls[0][1]).toBe('success');
      expect(btn.disabled).toBe(false);
    });

    it("says so when nothing was the system's, and when it could not be done", async () => {
      const { showToast } = await import('../toast.js');
      api.post.mockResolvedValueOnce({ status: 'ok', seen: 4, given: 0 });
      const btn = await open('/mnt/user/documents/Holiday');
      btn.click();
      await vi.waitFor(() => expect(showToast).toHaveBeenCalledTimes(1));
      expect(showToast.mock.calls[0][0]).toContain('Nothing in here still belonged to the system');
      api.post.mockRejectedValueOnce(new Error('forbidden'));
      btn.click();
      await vi.waitFor(() => expect(showToast).toHaveBeenCalledTimes(2));
      expect(showToast.mock.calls[1]).toEqual(['Failed updating permissions: forbidden', 'error']);
      expect(btn.disabled).toBe(false);
    });

    it('is offered for a folder only, and not for a protected one', async () => {
      expect(await open('/mnt/user/documents/report.pdf', false)).toBeNull();
      expect(await open('/mnt/user/appdata/mysql')).toBeNull();
    });
  });
});
