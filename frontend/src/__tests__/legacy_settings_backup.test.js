// Settings backups are .kibak files that start with KIBOBAK2; one made before the rename (old
// extension and marker) is still taken, and asks for its passphrase like any encrypted backup.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const api = await import('../api.js');
const { showPromptToast, showToast } = await import('../toast.js');
const settings = await import('../components/settings.js');
const { OLD_BACKUP_MAGIC, OLD_SETTINGS_EXT } = await import('../legacy-names.js');

const $ = (id) => document.getElementById(id);

beforeEach(() => {
  document.body.innerHTML =
    '<button id="btn-backup-download">Download</button><input type="file" id="backup-upload-input">';
  vi.spyOn(api.api, 'get').mockResolvedValue({});
  vi.spyOn(api.api, 'post').mockResolvedValue({});
});
afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

const upload = (file) => {
  const input = $('backup-upload-input');
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  input.dispatchEvent(new Event('change'));
};

describe('settings backup files', () => {
  it('a download the server gave no name is a .kibak file', async () => {
    vi.spyOn(api, 'apiFetch').mockResolvedValue(
      new Response(new Blob(['KIBOBAK2x']), { status: 200, headers: { 'content-type': 'application/octet-stream' } })
    );
    window.URL.createObjectURL = vi.fn(() => 'blob:x');
    window.URL.revokeObjectURL = vi.fn();
    const clicked = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
      clicked.push(this.download);
    });
    settings.initSystemTab();
    $('btn-backup-download').click();
    await vi.waitFor(() => expect(showPromptToast).toHaveBeenCalled());
    showPromptToast.mock.lastCall[3]('a long passphrase'); // confirm
    await vi.waitFor(() => expect(clicked.length).toBe(1));
    expect(clicked[0]).toMatch(/^kiboto_settings_.*\.kibak$/);
  });

  it('another kind of file is refused', async () => {
    settings.initSystemTab();
    upload(new File(['x'], 'notes.txt'));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.stringContaining('.kibak'), 'error'));
    expect(showPromptToast).not.toHaveBeenCalled();
  });

  it('a backup made before the rename still asks for its passphrase', async () => {
    settings.initSystemTab();
    upload(new File([`${OLD_BACKUP_MAGIC}rest`], `nas${OLD_SETTINGS_EXT}`));
    await vi.waitFor(() => expect(showPromptToast).toHaveBeenCalled());
    expect(showPromptToast.mock.lastCall[5].placeholder).toBe('Backup passphrase');
  });
});
