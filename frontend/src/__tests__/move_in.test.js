// Re-audit R5: "Bring your files over" from another NAS or a PC.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import {
  remoteName,
  parametersFor,
  targetPath,
  connect,
  listFolders,
  waitForJob,
  preview,
  copy,
  startMoveIn,
  openMoveIn,
} from '../components/move-in.js';

const noSleep = async () => {};
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('move in: the pieces', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('names the connection after the address and builds the fields', () => {
    expect(remoteName('192.168.1.20')).toBe('movein-192-168-1-20');
    expect(remoteName('Old NAS.local')).toBe('movein-old-nas-local');
    expect(remoteName('')).toBe('movein-source');
    expect(parametersFor('smb', { host: ' nas ', user: 'mara', pass: 'p w' })).toEqual({
      host: 'nas',
      user: 'mara',
      pass: 'p w',
    });
    expect(parametersFor('sftp', { host: 'nas' })).toEqual({ host: 'nas', user: '', pass: '', port: 22 });
  });

  it('puts a folder inside the shared folder under its own name', () => {
    expect(targetPath('/mnt/user/photos/', 'Pictures/2024')).toBe('/mnt/user/photos/2024');
    expect(targetPath('/mnt/user/photos', '')).toBe('/mnt/user/photos');
  });

  it('tests the connection before saving it, and passes on the other machine answer', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ success: true }).mockResolvedValueOnce({ status: 'ok' });
    expect(await connect('smb', { host: 'nas', user: 'mara', pass: 'x' })).toBe('movein-nas');
    expect(post.mock.calls[0][0]).toBe('/api/remotes/test');
    expect(post.mock.calls[1]).toEqual([
      '/api/remotes',
      { name: 'movein-nas', type: 'smb', parameters: { host: 'nas', user: 'mara', pass: 'x' } },
    ]);
    post.mockResolvedValueOnce({ success: false, error: 'logon failure' });
    await expect(connect('smb', { host: 'nas' })).rejects.toThrow('logon failure');
    post.mockResolvedValueOnce(null);
    await expect(connect('smb', { host: 'nas' })).rejects.toThrow('no answer');
  });

  it('lists folders only, sorted', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce([
      { Path: 'video', IsDir: true },
      { Path: 'readme.txt', IsDir: false },
      { Name: 'Photos', IsDir: true },
    ]);
    expect(await listFolders('movein-nas')).toEqual(['Photos', 'video']);
    vi.spyOn(api, 'get').mockResolvedValueOnce(null);
    expect(await listFolders('movein-nas')).toEqual([]);
  });

  it('waits for a job, reporting on the way; a dry run says what would move; a failed copy throws', async () => {
    const get = vi
      .spyOn(api, 'get')
      .mockResolvedValueOnce({ status: 'running', percent: 40 })
      .mockResolvedValueOnce({ status: 'success', percent: 100 });
    const seen = [];
    expect((await waitForJob('j1', (j) => seen.push(j.percent), noSleep)).status).toBe('success');
    expect(seen).toEqual([40, 100]);

    const post = vi.spyOn(api, 'post').mockResolvedValue({ id: 'j2' });
    get.mockResolvedValueOnce({ status: 'success', total_files: 12, total_bytes: 3000 });
    expect(await preview('movein-nas', 'Photos', '/mnt/user/photos/Photos', noSleep)).toEqual({
      files: 12,
      bytes: 3000,
    });
    expect(post).toHaveBeenLastCalledWith('/api/remotes/sync', {
      src: 'movein-nas:Photos',
      dst: '/mnt/user/photos/Photos',
      action: 'copy',
      dry_run: true,
      notify: false,
    });
    get.mockResolvedValueOnce({ status: 'success' });
    expect(await preview('movein-nas', 'Photos', '/x', noSleep)).toEqual({ files: 0, bytes: 0 });

    get.mockResolvedValueOnce({ status: 'error', error: '3 file(s) failed during transfer.' });
    await expect(copy('movein-nas', 'Photos', '/x', () => {}, noSleep)).rejects.toThrow('3 file(s) failed');
    get.mockResolvedValueOnce({ status: 'error' });
    await expect(copy('movein-nas', 'Photos', '/x', () => {}, noSleep)).rejects.toThrow('the copy stopped');
    expect(post.mock.calls.at(-1)[1]).toMatchObject({ dry_run: false, notify: true });
  });
});

describe('move in: the steps', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  const deps = (over = {}) => ({
    connect: vi.fn(async () => 'movein-nas'),
    listFolders: vi.fn(async () => ['Photos', 'video']),
    shares: vi.fn(async () => [{ name: 'photos', path: '/mnt/user/photos' }]),
    preview: vi.fn(async () => ({ files: 12, bytes: 3_000_000 })),
    copy: vi.fn(async (_n, _f, _t, onProgress) => {
      onProgress({ percent: 41.6, bytes_transferred: 1_250_000, total_bytes: 3_000_000 });
      return { status: 'success' };
    }),
    forget: vi.fn(async () => ({})),
    ...over,
  });
  const submit = (ui) => {
    /** @type {HTMLInputElement} */ (ui.form.querySelector('[name="host"]')).value = 'nas';
    ui.form.dispatchEvent(new Event('submit', { cancelable: true }));
  };
  const button = (root, text) => [...root.querySelectorAll('button')].find((b) => b.textContent === text);

  it('connects, previews, copies, checks and offers to forget the connection', async () => {
    const d = deps();
    d.preview
      .mockResolvedValueOnce({ files: 12, bytes: 3_000_000 })
      .mockResolvedValueOnce({ files: 12, bytes: 3_000_000 })
      .mockResolvedValueOnce({ files: 0, bytes: 0 }); // the check after the copy
    const ui = startMoveIn(document.body.appendChild(document.createElement('div')), d);
    submit(ui);
    await vi.waitFor(() => expect(ui.choose.hidden).toBe(false));
    expect(d.connect).toHaveBeenCalledWith('smb', { host: 'nas', user: '', pass: '' });
    expect(ui.form.hidden).toBe(true);
    const go = button(ui.choose, 'Copy now');
    expect(go.hidden).toBe(true); // not before the preview
    button(ui.choose, 'See what would be copied').click();
    await vi.waitFor(() => expect(go.hidden).toBe(false));
    expect(ui.status.textContent).toMatch(/^12 files \(2\.9 MB\) would be copied into \/mnt\/user\/photos\/Photos\.$/);
    /** @type {HTMLSelectElement} */ (ui.choose.querySelector('[name="from"]')).dispatchEvent(new Event('change'));
    expect(go.hidden).toBe(true); // another folder: look again first
    button(ui.choose, 'See what would be copied').click();
    await vi.waitFor(() => expect(go.hidden).toBe(false));
    go.click();
    await vi.waitFor(() => expect(ui.done.hidden).toBe(false));
    expect(d.copy.mock.calls[0].slice(0, 3)).toEqual(['movein-nas', 'Photos', '/mnt/user/photos/Photos']);
    expect(ui.status.textContent).toBe('Copied and checked: every file is in /mnt/user/photos/Photos.');
    button(ui.done, 'Forget the connection to the other machine').click();
    await vi.waitFor(() => expect(d.forget).toHaveBeenCalledWith('movein-nas'));
    await vi.waitFor(() => expect(ui.status.textContent).toContain('removed from this NAS'));
  });

  it('says what is still missing and lets the copy run again', async () => {
    const d = deps();
    d.preview.mockResolvedValueOnce({ files: 12, bytes: 3_000_000 }).mockResolvedValueOnce({ files: 1, bytes: 10 });
    const ui = startMoveIn(document.body.appendChild(document.createElement('div')), d);
    submit(ui);
    await vi.waitFor(() => expect(ui.choose.hidden).toBe(false));
    button(ui.choose, 'See what would be copied').click();
    await vi.waitFor(() => expect(button(ui.choose, 'Copy now').hidden).toBe(false));
    button(ui.choose, 'Copy now').click();
    await vi.waitFor(() => expect(ui.done.hidden).toBe(false));
    expect(ui.status.textContent).toMatch(/^1 file is still missing/);
    button(ui.done, 'Copy again').click();
    expect(ui.choose.hidden).toBe(false);
    expect(button(ui.choose, 'Copy now').disabled).toBe(false);
  });

  it('says why at each step that fails', async () => {
    const d = deps({
      connect: vi.fn(async () => {
        throw new Error('logon failure');
      }),
    });
    const ui = startMoveIn(document.body.appendChild(document.createElement('div')), d);
    submit(ui);
    await vi.waitFor(() => expect(ui.status.textContent).toBe("Couldn't connect: logon failure"));

    const none = startMoveIn(
      document.body.appendChild(document.createElement('div')),
      deps({ listFolders: async () => [] })
    );
    submit(none);
    await vi.waitFor(() => expect(none.status.textContent).toContain('sees no folders'));
    const noShare = startMoveIn(
      document.body.appendChild(document.createElement('div')),
      deps({ shares: async () => [] })
    );
    submit(noShare);
    await vi.waitFor(() => expect(noShare.status.textContent).toContain('Make a shared folder here first'));

    const d2 = deps({
      preview: vi
        .fn()
        .mockRejectedValueOnce(new Error('timeout'))
        .mockResolvedValueOnce({ files: 0, bytes: 0 })
        .mockResolvedValueOnce({ files: 3, bytes: 30 }),
      copy: vi.fn(async () => {
        throw new Error('disk full');
      }),
      forget: vi.fn(async () => {
        throw new Error('busy');
      }),
    });
    const ui2 = startMoveIn(document.body.appendChild(document.createElement('div')), d2);
    submit(ui2);
    await vi.waitFor(() => expect(ui2.choose.hidden).toBe(false));
    const look = button(ui2.choose, 'See what would be copied');
    look.click();
    await vi.waitFor(() => expect(ui2.status.textContent).toBe("Couldn't compare the two sides: timeout"));
    look.click();
    await vi.waitFor(() => expect(ui2.status.textContent).toBe('Everything in that folder is already here.'));
    look.click();
    await vi.waitFor(() => expect(button(ui2.choose, 'Copy now').hidden).toBe(false));
    button(ui2.choose, 'Copy now').click();
    await vi.waitFor(() => expect(ui2.status.textContent).toContain("didn't finish: disk full"));
    expect(look.disabled).toBe(false);
  });

  it('a failed forget says so', async () => {
    const d = deps({
      forget: vi.fn(async () => {
        throw new Error('busy');
      }),
    });
    d.preview.mockResolvedValueOnce({ files: 2, bytes: 20 }).mockResolvedValueOnce({ files: 0, bytes: 0 });
    const ui = startMoveIn(document.body.appendChild(document.createElement('div')), d);
    submit(ui);
    await vi.waitFor(() => expect(ui.choose.hidden).toBe(false));
    button(ui.choose, 'See what would be copied').click();
    await vi.waitFor(() => expect(button(ui.choose, 'Copy now').hidden).toBe(false));
    button(ui.choose, 'Copy now').click();
    await vi.waitFor(() => expect(ui.done.hidden).toBe(false));
    button(ui.done, 'Forget the connection to the other machine').click();
    await vi.waitFor(() => expect(ui.status.textContent).toBe("Couldn't remove the connection: busy"));
  });

  it('opens as a window, once, and closes with its button, Escape and the backdrop', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      shares: [{ name: 'photos', mountpoint: '/mnt/user/photos' }, { name: 'x' }],
    });
    const host = openMoveIn();
    expect(host.classList.contains('open')).toBe(true);
    expect(host.querySelector('[role="dialog"]').getAttribute('aria-labelledby')).toBe('move-in-title');
    expect(document.activeElement).toBe(host.querySelector('input[name="host"]'));
    /** @type {HTMLElement} */ (host.querySelector('.close-btn')).click();
    expect(host.classList.contains('open')).toBe(false);
    expect(openMoveIn()).toBe(host);
    host.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(host.style.display).toBe('none');
    openMoveIn();
    host.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }));
    host.querySelector('.smart-modal-window').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(host.classList.contains('open')).toBe(true);
    host.click();
    expect(host.classList.contains('open')).toBe(false);
    await flush();
  });
});
