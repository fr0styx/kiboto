/** SET-22 Storage 3: WebDAV is a way into this NAS, so it sits on Shared folders -> Other ways to
 *  connect, beside SFTP; Cloud drives keeps only the outbound cloud accounts. */
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../utils.js', async (orig) => ({ ...(await orig()), copyTextToClipboard: vi.fn() }));
const utils = await import('../utils.js');
const { api } = await import('../api.js');
const { fetchAndRenderNetworkShares, fetchAndRenderRemoteStorage, renderWebdavCard } =
  await import('../components/chassis-visualizer.js');
const flush = () => new Promise((r) => setTimeout(r, 0));

const WEBDAV = {
  running: true,
  port: 8084,
  root_path: '/mnt/user',
  read_only: false,
  quick_connect: { windows: 'net use Z: x' },
};

function routes(webdav) {
  vi.spyOn(api, 'get').mockImplementation(async (url) => {
    if (url === '/api/storage/shares') return { shares: [], platform: 'generic_linux' };
    if (url === '/api/storage/platform')
      return { platform: 'generic_linux', capabilities: { can_manage_shares: true } };
    if (url === '/api/sftp/status') return { running: false, port: 2222 };
    if (url === '/api/sftp/users') return [];
    if (url === '/api/samba/status') return null;
    if (url === '/api/webdav/status') return webdav;
    if (url === '/api/remotes') return [];
    throw new Error(url);
  });
}

describe('WebDAV on Shared folders (SET-22 Storage 3)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('draws the WebDAV card under Other ways to connect, beside SFTP', async () => {
    document.body.innerHTML =
      '<div id="shares"></div><details><div id="shares-sftp-mount"></div><div id="shares-webdav-mount"></div></details>';
    routes(WEBDAV);
    await fetchAndRenderNetworkShares(document.getElementById('shares'));
    const mount = /** @type {HTMLElement} */ (document.getElementById('shares-webdav-mount'));
    expect(mount.querySelector('#mgmt-webdav-card')).not.toBeNull();
    expect(mount.textContent).toContain('WebDAV file server');
    expect(mount.textContent).toContain('net use Z: x');
    expect(document.getElementById('shares-sftp-mount')?.querySelector('#mgmt-sftp-subsystem-card')).not.toBeNull();
  });

  it('leaves the place empty when the server does not answer for WebDAV', async () => {
    document.body.innerHTML =
      '<div id="shares"></div><div id="shares-sftp-mount"></div><div id="shares-webdav-mount"></div>';
    routes(null);
    await fetchAndRenderNetworkShares(document.getElementById('shares'));
    expect(document.getElementById('shares-webdav-mount')?.innerHTML).toBe('');
  });

  it('Cloud drives shows only the cloud drives', async () => {
    document.body.innerHTML = '<div id="clouds"></div>';
    routes(WEBDAV);
    const box = /** @type {HTMLElement} */ (document.getElementById('clouds'));
    await fetchAndRenderRemoteStorage(box);
    expect(box.textContent).toContain('No cloud drives connected');
    expect(box.textContent).not.toContain('WebDAV');
    expect(api.get).not.toHaveBeenCalledWith('/api/webdav/status');
  });

  it('a stopped server starts, restarts, opens its settings and copies an address', async () => {
    document.body.innerHTML = `<div id="w"></div>
      <div id="modal-webdav-config" style="display:none"><form id="webdav-config-form"><input id="webdav-cfg-port"><input id="webdav-cfg-root">
      <input id="webdav-cfg-user"><input id="webdav-cfg-pass"><input type="checkbox" id="webdav-cfg-readonly-toggle">
      <button id="modal-webdav-close-btn" type="button"></button><button id="modal-webdav-cancel-btn" type="button"></button></form></div>`;
    const host = /** @type {HTMLElement} */ (document.getElementById('w'));
    const refresh = vi.fn();
    const post = vi.spyOn(api, 'post').mockResolvedValue({});
    renderWebdavCard(
      host,
      {
        running: false,
        port: 8085,
        root_path: '/mnt/user',
        read_only: true,
        quick_connect: { windows: 'net use Z: y' },
      },
      refresh
    );
    expect(host.textContent).toContain('Stopped');
    /** @type {HTMLButtonElement} */ (host.querySelector('#btn-webdav-toggle')).click();
    await flush();
    expect(post).toHaveBeenCalledWith('/api/webdav/toggle', { enabled: true });
    /** @type {HTMLButtonElement} */ (host.querySelector('#btn-webdav-restart')).click();
    await flush();
    expect(post).toHaveBeenCalledWith('/api/webdav/restart');
    expect(refresh).toHaveBeenCalledTimes(2);
    /** @type {HTMLButtonElement} */ (host.querySelector('#btn-webdav-config-open')).click();
    expect(/** @type {HTMLElement} */ (document.getElementById('modal-webdav-config')).style.display).not.toBe('none');
    vi.mocked(utils.copyTextToClipboard).mockResolvedValueOnce(true).mockResolvedValueOnce(false);
    const copy = /** @type {HTMLButtonElement} */ (host.querySelector('.btn-qc-copy[data-copy="net use Z: y"]'));
    copy.click();
    await flush();
    copy.click();
    await flush();
    expect(utils.copyTextToClipboard).toHaveBeenCalledWith('net use Z: y');
  });

  it('says when Start or Restart fails', async () => {
    document.body.innerHTML = '<div id="w"></div>';
    const host = /** @type {HTMLElement} */ (document.getElementById('w'));
    vi.spyOn(api, 'post').mockRejectedValue(new Error('no port'));
    const refresh = vi.fn();
    renderWebdavCard(host, { running: true, port: 8084, root_path: '/mnt/user', quick_connect: {} }, refresh);
    /** @type {HTMLButtonElement} */ (host.querySelector('#btn-webdav-toggle')).click();
    /** @type {HTMLButtonElement} */ (host.querySelector('#btn-webdav-restart')).click();
    await flush();
    expect(refresh).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('no port');
  });
});
